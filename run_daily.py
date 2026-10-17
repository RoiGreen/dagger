"""
Data update, run by Windows Task Scheduler ("NBA Fantasy Daily Update") with pythonw.exe, so there is no console
window to be closed half way: every 3 hours from 09:00, when Roi logs on, and when the computer wakes from sleep.

    pythonw run_daily.py        (or: python run_daily.py, to run it by hand)

Steps: git pull -> daily_update.py (game logs, schedule, rosters, headshots, injuries, positions, logos)
-> build_dashboard.py -> commit and push the website. Every line goes to logs/daily_update.log as it happens.
(run_daily.ps1 does the same from PowerShell; the scheduled task uses this file.)
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
LOG = HERE / "logs" / "daily_update.log"
PY = str(Path(sys.executable).with_name("python.exe"))  # the console python, run without a window
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", GIT_TERMINAL_PROMPT="0")
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def log(message: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}\n")


def run(label: str, args: list[str], check: bool = True) -> int:
    log(f"{label}...")
    p = subprocess.Popen(args, cwd=HERE, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    with LOG.open("a", encoding="utf-8") as f:
        for line in p.stdout:
            f.write(line)
            f.flush()
    code = p.wait()
    if check and code != 0:
        log(f"{label} failed (exit {code})")
        sys.exit(1)  # the task retries a failed run after 15 minutes
    return code


def main() -> None:
    LOG.parent.mkdir(exist_ok=True)
    # Keep the log short: the last ~400 lines are enough to see what happened
    if LOG.exists():
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > 600:
            LOG.write_text("\n".join(lines[-400:]) + "\n", encoding="utf-8")
    log("start")
    run("sync", ["git", "pull", "-q", "--rebase", "--autostash"])  # the cloud refreshes injuries during the day
    run("pull data", [PY, "daily_update.py"])
    run("build", [PY, "build_dashboard.py"])
    # the schedule (results), rosters, new photos and logos go up too: the cloud update rebuilds the site from them
    subprocess.run(["git", "add", "-A", "--", "nba_2026_27", "docs", "draft_dashboard.html", "nba_2025_26/schedule_2026_27.csv",
                    "nba_2025_26/player_index_2026_27.csv", "nba_2025_26/headshots_hd", "nba_2025_26/team_logos"],
                   cwd=HERE, env=ENV, creationflags=NO_WINDOW)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=HERE, env=ENV, creationflags=NO_WINDOW).returncode == 0:
        log("no new data")
    else:
        run("commit", ["git", "commit", "-q", "-m", f"Daily data update {datetime.now():%Y-%m-%d %H:%M}"])
        run("sync", ["git", "pull", "-q", "--rebase", "--autostash"])
        run("push", ["git", "push", "-q"])
        log("pushed")
    log("done")


if __name__ == "__main__":
    main()
