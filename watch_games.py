"""
Game watcher, run by Windows Task Scheduler ("NBA Fantasy Game Watcher") with pythonw.exe every 10 minutes while
Roi is logged on (it never wakes the computer). It reads the schedule already on disk: when a game has ended
(~2.5 hours after tip-off) and its box score is not in the game logs yet, it runs run_daily.py, so the website
gets the result about 20-40 minutes after the final buzzer. No finished game missing -> it exits without
touching the network.

    pythonw watch_games.py
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
LOG = HERE / "logs" / "daily_update.log"
STATE = HERE / "logs" / "watch_state.json"  # update attempts per game, so a game with no box score is not chased forever
SCHEDULE = HERE / "nba_2025_26" / "schedule_2026_27.csv"
GAME_LOGS = [HERE / "nba_2026_27" / f"game_logs_{tag}.csv" for tag in ("preseason", "regular")]
GAME_LENGTH = timedelta(hours=2, minutes=30)
LOOKBACK = timedelta(hours=18)  # older games are left to the regular update
MAX_TRIES = 8                   # 8 tries x 10 minutes: stats.nba.com usually has the box score within 30


def log(message: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  watcher: {message}\n")


def logged_games() -> set[str]:
    ids = set()
    for path in GAME_LOGS:
        if path.exists() and path.stat().st_size > 0:
            try:
                ids |= set(pd.read_csv(path, dtype=str, usecols=["GAME_ID"]).GAME_ID)
            except (ValueError, pd.errors.EmptyDataError):
                pass
    return ids


def main() -> None:
    if not SCHEDULE.exists():
        return
    now = datetime.now(timezone.utc)
    s = pd.read_csv(SCHEDULE, dtype=str, usecols=["gameId", "gameDateTimeUTC", "postponedStatus"])
    s["start"] = pd.to_datetime(s.gameDateTimeUTC, utc=True, errors="coerce")
    ended = s[(s.start + GAME_LENGTH <= now) & (s.start >= now - LOOKBACK) & (s.postponedStatus.fillna("N") == "N")]
    if ended.empty:
        return
    missing = sorted(set(ended.gameId) - logged_games())
    try:
        tries = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except ValueError:
        tries = {}
    tries = {g: n for g, n in tries.items() if g in set(ended.gameId)}  # forget games out of the window
    todo = [g for g in missing if tries.get(g, 0) < MAX_TRIES]
    if not todo:
        STATE.write_text(json.dumps(tries), encoding="utf-8")
        return
    # another update is running (the log was written in the last 3 minutes): try again on the next tick
    if LOG.exists() and datetime.now().timestamp() - LOG.stat().st_mtime < 180:
        return
    for g in todo:
        tries[g] = tries.get(g, 0) + 1
    STATE.write_text(json.dumps(tries), encoding="utf-8")
    log(f"{len(todo)} finished game(s) not on the site yet ({', '.join(todo)}): updating")
    subprocess.run([sys.executable, str(HERE / "run_daily.py")], cwd=HERE, creationflags=0x08000000)


if __name__ == "__main__":
    main()
