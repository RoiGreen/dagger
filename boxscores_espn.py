"""
Box scores from ESPN for games that have ended but are not in the NBA game logs yet, into
./nba_2026_27/game_logs_espn.csv (same columns as the NBA logs) and ./nba_2026_27/starters_espn.json.

    python boxscores_espn.py

Run by the GitHub Actions workflow after scores_espn.py, so last night's box scores, the player card's last games and
the matchup's "so far" reach the site even when Roi's computer is off (stats.nba.com blocks GitHub's servers; ESPN
does not). build_dashboard.py uses these rows only for games the NBA logs do not have, so once the daily run on this
computer brings the official logs, they take over. ESPN players are matched to NBA player ids by name and team;
a player that cannot be matched is left out (and named in the output).
"""

import json
import re
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

HERE = Path(__file__).parent
SCHEDULE = HERE / "nba_2025_26" / "schedule_2026_27.csv"
ROSTER = HERE / "nba_2025_26" / "player_index_2026_27.csv"
NBA_LOGS = [HERE / "nba_2026_27" / "game_logs_preseason.csv", HERE / "nba_2026_27" / "game_logs_regular.csv"]
OUT = HERE / "nba_2026_27" / "game_logs_espn.csv"
OUT_STARTERS = HERE / "nba_2026_27" / "starters_espn.json"
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={}"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={}"
ET = ZoneInfo("America/New_York")
LOOKBACK = timedelta(days=4)
ESPN_TO_NBA = {"GS": "GSW", "SA": "SAS", "NO": "NOP", "NY": "NYK", "WSH": "WAS", "UTAH": "UTA", "PHO": "PHX"}
COLS = ["SEASON_YEAR", "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_ABBREVIATION", "GAME_ID", "GAME_DATE", "MATCHUP", "WL",
        "MIN", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", "REB", "AST", "TOV", "STL", "BLK", "PF", "PTS",
        "PLUS_MINUS"]


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def key(name: str) -> str:
    """A name for matching: no accents, punctuation or suffixes ("Nikola Jokić" = "Nikola Jokic", "Jr." dropped)."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s.replace("-", " "))
    return " ".join(w for w in s.split() if w not in {"jr", "sr", "ii", "iii", "iv"})


def nba_players() -> tuple[dict, dict]:
    """(team, name key) -> NBA id, and name key -> NBA id when the name is unique; from the rosters and the logs."""
    rows = []
    if ROSTER.exists():
        r = pd.read_csv(ROSTER, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        rows += [(t, f"{f} {l}", int(i), f"{f} {l}") for i, f, l, t in
                 zip(r["PERSON_ID"], r["PLAYER_FIRST_NAME"], r["PLAYER_LAST_NAME"], r["TEAM_ABBREVIATION"])]
    for f in NBA_LOGS:
        if f.exists() and f.stat().st_size > 200:
            g = pd.read_csv(f, usecols=["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION"]).drop_duplicates()
            rows += [(t, n, int(i), n) for i, n, t in zip(g["PLAYER_ID"], g["PLAYER_NAME"], g["TEAM_ABBREVIATION"])]
    by_team, by_name, names = {}, {}, {}
    for team, name, pid, shown in rows:
        k = key(name)
        by_team[(team, k)] = pid
        by_name.setdefault(k, set()).add(pid)
        names[pid] = shown
    return by_team, {k: next(iter(v)) for k, v in by_name.items() if len(v) == 1}, names


def game_rows(gid: str, sched_row, event_id: str, players) -> tuple[list[dict], dict, list[str]]:
    """The game's player lines in the NBA log columns, its starters {id: G/F/C}, and the names not matched."""
    by_team, by_name, names = players
    box = get(SUMMARY.format(event_id))["boxscore"]["players"]
    home, away = sched_row["homeTeam_teamTricode"], sched_row["awayTeam_teamTricode"]
    hs, as_ = int(sched_row["homeTeam_score"]), int(sched_row["awayTeam_score"])
    day = pd.Timestamp(sched_row["gameDateTimeUTC"]).tz_convert(ET).strftime("%Y-%m-%d")
    rows, starters, missed = [], {}, []
    for side in box:
        team = ESPN_TO_NBA.get(side["team"]["abbreviation"], side["team"]["abbreviation"])
        is_home = team == home
        opp = away if is_home else home
        won = (hs > as_) == is_home
        st = side["statistics"][0]
        ix = {l: i for i, l in enumerate(st["labels"])}
        for a in st["athletes"]:
            s = a.get("stats") or []
            if a.get("didNotPlay") or not s or not s[ix["MIN"]].strip("-"):
                continue
            nm = a["athlete"]["displayName"]
            pid = by_team.get((team, key(nm))) or by_name.get(key(nm))
            if not pid:
                missed.append(f"{nm} ({team})")
                continue
            made = lambda lbl: [int(x) for x in s[ix[lbl]].split("-")]  # noqa: E731
            (fgm, fga), (f3m, f3a), (ftm, fta) = made("FG"), made("3PT"), made("FT")
            n = lambda lbl: int(s[ix[lbl]] or 0)  # noqa: E731
            rows.append({
                "SEASON_YEAR": "2026-27", "PLAYER_ID": pid, "PLAYER_NAME": names.get(pid, nm), "TEAM_ID": "",
                "TEAM_ABBREVIATION": team, "GAME_ID": gid, "GAME_DATE": day,
                "MATCHUP": f"{team} vs. {opp}" if is_home else f"{team} @ {opp}", "WL": "W" if won else "L",
                "MIN": float(s[ix["MIN"]]), "FGM": fgm, "FGA": fga, "FG3M": f3m, "FG3A": f3a, "FTM": ftm, "FTA": fta,
                "OREB": n("OREB"), "DREB": n("DREB"), "REB": n("REB"), "AST": n("AST"), "TOV": n("TO"), "STL": n("STL"),
                "BLK": n("BLK"), "PF": n("PF"), "PTS": n("PTS"), "PLUS_MINUS": int(s[ix["+/-"]].replace("+", "") or 0),
            })
            if a.get("starter"):
                pos = (a["athlete"].get("position") or {}).get("abbreviation", "")
                starters[str(pid)] = {"PG": "G", "SG": "G", "SF": "F", "PF": "F"}.get(pos, pos[:1])
    return rows, starters, missed


def fill_boxscores() -> str:
    sched = pd.read_csv(SCHEDULE, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    now = datetime.now(timezone.utc)
    tip = pd.to_datetime(sched["gameDateTimeUTC"], utc=True, errors="coerce")
    logged = set()
    for f in NBA_LOGS:
        if f.exists() and f.stat().st_size > 200:
            logged |= set(pd.read_csv(f, usecols=["GAME_ID"], dtype=str)["GAME_ID"].str.zfill(10))
    final = sched[(sched["gameStatus"] == "3") & (tip > now - LOOKBACK)]
    missing = {str(g).zfill(10): i for g, i in zip(final["gameId"], final.index) if str(g).zfill(10) not in logged}
    # rows kept from earlier runs: only games still missing from the NBA logs
    old = pd.read_csv(OUT, dtype={"GAME_ID": str}) if OUT.exists() and OUT.stat().st_size > 0 else pd.DataFrame(columns=COLS)
    old = old[old["GAME_ID"].isin(missing)]
    starters = json.loads(OUT_STARTERS.read_text(encoding="utf-8")) if OUT_STARTERS.exists() else {}
    starters = {g: v for g, v in starters.items() if g in missing}
    todo = [g for g in missing if g not in set(old["GAME_ID"])]
    new_rows, missed, done = [], [], 0
    if todo:
        try:
            players = nba_players()
            boards = {}
            for gid in todo:
                r = sched.loc[missing[gid]]
                d = tip[missing[gid]].astimezone(ET).strftime("%Y%m%d")
                if d not in boards:
                    boards[d] = get(SCOREBOARD.format(d)).get("events", [])
                ev = next((e for e in boards[d] if {ESPN_TO_NBA.get(c["team"]["abbreviation"], c["team"]["abbreviation"])
                                                    for c in e["competitions"][0]["competitors"]}
                           == {r["homeTeam_teamTricode"], r["awayTeam_teamTricode"]}), None)
                if not ev:
                    continue
                rows, st, miss = game_rows(gid, r, ev["id"], players)
                if rows:
                    new_rows += rows; starters[gid] = st; missed += miss; done += 1
        except Exception as e:  # noqa: BLE001
            return f"Box scores (ESPN): pull failed ({e}), kept the previous ones"
    out = pd.concat([old, pd.DataFrame(new_rows, columns=COLS)], ignore_index=True) if new_rows else old
    out[COLS].to_csv(OUT, index=False, encoding="utf-8-sig")
    OUT_STARTERS.write_text(json.dumps(starters, ensure_ascii=False), encoding="utf-8")
    msg = f"Box scores (ESPN): {done} new, {out['GAME_ID'].nunique()} games waiting for the NBA logs"
    return msg + (f"; not matched: {', '.join(missed)}" if missed else "")


if __name__ == "__main__":
    print(fill_boxscores())
