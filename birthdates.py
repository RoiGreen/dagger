"""
Birth dates of every player on a 2026-27 roster and of the 2026 draft class, so the page shows each player's
real age on the day it is opened (the season files only carry the age during that season).

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
ROSTERS = HERE / "nba_2025_26" / "player_index_2026_27.csv"


def pull_birthdates() -> str:
    have = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    ids = [str(int(x)) for x in pd.read_csv(ROOKIES)["PLAYER_ID"]] if ROOKIES.exists() else []
    if ROSTERS.exists():
        ids += [str(int(x)) for x in pd.read_csv(ROSTERS)["PERSON_ID"]]
    ids = list(dict.fromkeys(ids))
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
            if new % 50 == 0:  # keep what we have if a long first run is cut off
                OUT.write_text(json.dumps(have, separators=(",", ":")), encoding="utf-8")
    OUT.write_text(json.dumps(have, separators=(",", ":")), encoding="utf-8")
    return f"Birth dates: {len(have)} ({new} new{f', {failed} failed' if failed else ''})"


if __name__ == "__main__":
    print(pull_birthdates())
