"""
Birth dates of the 2026 draft class, so a rookie's age is his real age today (the projection file carries
the age of his last college / overseas season, and is blank for some international picks).

    python birthdates.py

Writes ./nba_2026_27/birthdates.json: {player id: "YYYY-MM-DD"}. A birth date never changes, so each player is
asked for once. Source: stats.nba.com player profile (commonplayerinfo).
"""

import json
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import commonplayerinfo

from nba_stats_2025_26 import fetch

HERE = Path(__file__).parent
OUT = HERE / "nba_2026_27" / "birthdates.json"
ROOKIES = HERE / "rookie_projections_2026_27.csv"


def pull_birthdates() -> str:
    have = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    ids = [str(int(x)) for x in pd.read_csv(ROOKIES)["PLAYER_ID"]] if ROOKIES.exists() else []
    new = failed = 0
    for pid in ids:
        if pid in have:
            continue
        try:
            info = fetch(commonplayerinfo.CommonPlayerInfo, player_id=pid)
        except RuntimeError:
            failed += 1
            continue
        b = str(info.iloc[0].get("BIRTHDATE") or "")[:10]
        if b:
            have[pid] = b
            new += 1
    OUT.write_text(json.dumps(have, separators=(",", ":")), encoding="utf-8")
    return f"Rookie birth dates: {len(have)} ({new} new{f', {failed} failed' if failed else ''})"


if __name__ == "__main__":
    print(pull_birthdates())
