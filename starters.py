"""
Starting lineups for every 2026-27 game in the game logs (the box score marks the five starters).

    python starters.py

Writes ./nba_2026_27/starters.json: {game id: {player id: starting position (G / F / C)}}.
A finished game never changes, so each game is downloaded once. Source: stats.nba.com box score.
"""

import json
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import boxscoretraditionalv3

from nba_stats_2025_26 import fetch

HERE = Path(__file__).parent
OUT = HERE / "nba_2026_27"
STARTERS = OUT / "starters.json"
LOGS = [OUT / "game_logs_preseason.csv", OUT / "game_logs_regular.csv"]


def pull_starters() -> str:
    have = json.loads(STARTERS.read_text(encoding="utf-8")) if STARTERS.exists() else {}
    games = set()
    for f in LOGS:
        if f.exists() and f.stat().st_size > 200:
            games |= {str(g).zfill(10) for g in pd.read_csv(f, dtype={"GAME_ID": str})["GAME_ID"].unique()}
    new, failed = 0, 0
    for gid in sorted(games - set(have)):
        try:
            df = fetch(boxscoretraditionalv3.BoxScoreTraditionalV3, game_id=gid)
        except RuntimeError:
            failed += 1
            continue
        # each team lists its starting five first (a few bench players can carry a position too: ignore them)
        df = df[df["position"].fillna("").str.strip() != ""]
        five = df.groupby("teamTricode", sort=False).head(5)
        if len(five) < 10:  # box score not final yet: try again next run
            continue
        have[gid] = {str(int(r.personId)): r.position.strip() for r in five.itertuples()}
        new += 1
    STARTERS.write_text(json.dumps(have, separators=(",", ":")), encoding="utf-8")
    return f"Starting lineups: {len(have)} games ({new} new{f', {failed} failed' if failed else ''})"


if __name__ == "__main__":
    print(pull_starters())
