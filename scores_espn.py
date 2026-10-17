"""
Fill in final scores from ESPN's scoreboard in ./nba_2025_26/schedule_2026_27.csv, for games that have ended but
are not marked final yet (the score bar at the top of the site reads them).

    python scores_espn.py

Run by the GitHub Actions workflow in the morning, so last night's results reach the site even when Roi's computer
is off (stats.nba.com, which the daily run uses, blocks GitHub's servers; ESPN does not). The daily run on this
computer later rewrites the whole schedule from the NBA, with the same results. Only games that ESPN marks final are
changed, and only from "not final" to final. A failed pull changes nothing.
"""

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

HERE = Path(__file__).parent
SCHEDULE = HERE / "nba_2025_26" / "schedule_2026_27.csv"
URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={}"
ET = ZoneInfo("America/New_York")
LOOKBACK = timedelta(days=3)  # older games are left to the daily run
GAME_LENGTH = timedelta(hours=2)
# ESPN's team codes that differ from the NBA's
ESPN_TO_NBA = {"GS": "GSW", "SA": "SAS", "NO": "NOP", "NY": "NYK", "WSH": "WAS", "UTAH": "UTA", "PHO": "PHX"}


def espn_finals(day: str) -> dict:
    """{(home, away): (home score, away score)} for the games ESPN marks final on a US date (YYYYMMDD)."""
    req = urllib.request.Request(URL.format(day), headers={"User-Agent": "Mozilla/5.0"})
    data = json.load(urllib.request.urlopen(req, timeout=60))
    out = {}
    for ev in data.get("events", []):
        comp = ev["competitions"][0]
        if not comp["status"]["type"].get("completed"):
            continue
        side = {c["homeAway"]: c for c in comp["competitors"]}
        code = lambda c: ESPN_TO_NBA.get(c["team"]["abbreviation"], c["team"]["abbreviation"])  # noqa: E731
        out[(code(side["home"]), code(side["away"]))] = (int(side["home"]["score"]), int(side["away"]["score"]))
    return out


def fill_scores() -> str:
    # every column as text, so the file is written back exactly as it was apart from the filled games
    sched = pd.read_csv(SCHEDULE, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    now = datetime.now(timezone.utc)
    tip = pd.to_datetime(sched["gameDateTimeUTC"], utc=True, errors="coerce")
    open_games = sched.index[(sched["gameStatus"] != "3") & (tip < now - GAME_LENGTH) & (tip > now - LOOKBACK)]
    if not len(open_games):
        return "Scores: nothing to fill"
    days = sorted({tip[i].astimezone(ET).strftime("%Y%m%d") for i in open_games})
    finals = {}
    try:
        for d in days:
            finals[d] = espn_finals(d)
    except Exception as e:  # noqa: BLE001
        return f"Scores: ESPN pull failed ({e}), nothing changed"
    filled = 0
    for i in open_games:
        r = sched.loc[i]
        got = finals[tip[i].astimezone(ET).strftime("%Y%m%d")].get((r["homeTeam_teamTricode"], r["awayTeam_teamTricode"]))
        if not got:
            continue
        sched.loc[i, ["gameStatus", "gameStatusText", "homeTeam_score", "awayTeam_score"]] = ["3", "Final", str(got[0]), str(got[1])]
        filled += 1
    if filled:
        sched.to_csv(SCHEDULE, index=False, encoding="utf-8-sig")
    return f"Scores: {filled} of {len(open_games)} ended games filled from ESPN"


if __name__ == "__main__":
    print(fill_scores())
