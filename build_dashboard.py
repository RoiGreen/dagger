"""
Build the draft-night dashboard from the downloaded stats.

Run nba_stats_2025_26.py first, then:
    python build_dashboard.py

Reads dashboard_template.html, embeds the player data and writes draft_dashboard.html.
Every player carries his 2023-24, 2024-25 and 2025-26 lines; the page picks the seasons to use,
so rankings, the advanced tab, the team table and the importance panel all follow the season choice.
"""

import base64
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "nba_2025_26"
TEMPLATE = HERE / "dashboard_template.html"
OUT = HERE / "draft_dashboard.html"
# Standalone website for GitHub Pages, with Supabase accounts (built when site_config.json is filled in)
SITE_CONFIG = HERE / "site_config.json"
SITE_OUT = HERE / "docs" / "index.html"
SUPABASE_JS = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.117.2/dist/umd/supabase.min.js"
SITE_RESET = ("html{color-scheme:light dark}body{margin:0;font:14px/1.45 system-ui,-apple-system,'Segoe UI',sans-serif}"
              "img{max-width:100%}[hidden]{display:none!important}")

SEASON_MIN_GP = 5  # a season counts for a player once he played this many games in it
STATS = ["MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV", "FGM", "FGA", "FTM", "FTA"]
ADV = ["USG_PCT", "PACE", "OFF_RATING"]
TEAM_ADV = ["PACE", "OFF_RATING", "DEF_RATING", "NET_RATING"]

# Players who missed most of 2025-26 are shown with their last full season instead
PREVIOUS_SEASONS = ["2024-25", "2023-24"]
INJURED_MAX_GP = 25   # fewer games than this in 2025-26
FULL_SEASON_GP = 40   # what counts as a full season before that
FULL_ROLE_MIN = 25    # and a real role in it
INJURED_CSV = HERE / "injured_last_full_season.csv"
ROOKIE_CSV = HERE / "rookie_projections_2026_27.csv"
BIRTHDATES = HERE / "nba_2026_27" / "birthdates.json"  # rookies' birth dates (birthdates.py)


def age_on(birth: str, day=None) -> int:
    """Whole years from a YYYY-MM-DD birth date to today."""
    from datetime import date
    b, d = date.fromisoformat(birth[:10]), day or date.today()
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))
# Seasons the page can choose from, by start year, and their files
AVAIL_SEASONS = [2023, 2024, 2025]
SEASON_TAG = {2023: "_2023_24", 2024: "_2024_25", 2025: ""}  # 2025-26 files carry no suffix
# 2026-27, built from the daily game logs (daily_update.py). The regular season is keyed 2026 like the
# other seasons; the preseason gets its own key so the two can be chosen separately.
CURRENT = 2026
CURRENT_LOGS = HERE / "nba_2026_27" / "game_logs_regular.csv"
PRESEASON = 1026
PRESEASON_LOGS = HERE / "nba_2026_27" / "game_logs_preseason.csv"
STARTERS = HERE / "nba_2026_27" / "starters.json"  # starting lineups per game (starters.py)
INJURIES_CSV = HERE / "nba_2026_27" / "injuries.csv"  # ESPN injury list, from injuries.py
POSITIONS_CSV = HERE / "nba_2026_27" / "positions_espn.csv"  # ESPN fantasy positions, from positions.py
# For players ESPN does not list yet (mostly rookies): the NBA's broad position turned into fantasy positions
NBA_TO_FANTASY = {"G": "PG/SG", "F": "SF/PF", "C": "C", "G-F": "SG/SF", "F-G": "SG/SF", "F-C": "PF/C", "C-F": "PF/C"}
INJURIES_STAMP = HERE / "nba_2026_27" / "injuries_updated.txt"
HEADSHOTS = DATA / "headshots_hd"  # 120x120 WebP headshots from headshots.py
# Head-to-head: the last N regular-season games against each opponent, 2025-26 and 2026-27
VS_GAMES = 4
GAME_LOG_FILES = [DATA / "player_game_logs_regular.csv", CURRENT_LOGS]
# the NBA's per-game advanced lines for the same games (USG%, pace, offensive rating, possessions)
ADV_GAME_FILES = [DATA / "player_game_logs_advanced_regular.csv", HERE / "nba_2026_27" / "game_logs_advanced_regular.csv"]


def adv_games() -> pd.DataFrame:
    frames = [pd.read_csv(f, dtype={"GAME_ID": str}) for f in ADV_GAME_FILES if f.exists() and f.stat().st_size > 100]
    if not frames:
        return pd.DataFrame(columns=["PLAYER_ID", "GAME_ID", "MIN", "POSS"] + ADV)
    g = pd.concat(frames, ignore_index=True)
    g["GAME_ID"] = g["GAME_ID"].str.zfill(10)
    return g[g["MIN"] > 0]


def adv_over(rows: pd.DataFrame, keys: list[str]) -> dict:
    """USG% / pace / offensive rating over a set of games, per key: usage and rating weighted by possessions,
    pace by minutes (matches the NBA's season table within ~0.1)."""
    if rows.empty:
        return {}
    r = rows.assign(u=rows["USG_PCT"] * rows["POSS"], p=rows["PACE"] * rows["MIN"], o=rows["OFF_RATING"] * rows["POSS"])
    t = r.groupby(keys)[["u", "p", "o", "POSS", "MIN"]].sum()
    t = t[(t["POSS"] > 0) & (t["MIN"] > 0)]
    return {k: [round(float(x.u / x.POSS), 3), round(float(x.p / x.MIN), 3), round(float(x.o / x.POSS), 3)] for k, x in t.iterrows()}
SEASON_FILES = HERE / "nba_2025_26" / "rookies"


# Per-game fantasy-point weights (ESPN points league), for the team distribution panel
DIST_FP = {"PTS": 1, "FG3M": 1, "FGA": -1, "FGM": 2, "FTA": -1, "FTM": 1, "REB": 1, "AST": 2, "STL": 4, "BLK": 4, "TOV": -2}


def team_distribution() -> dict:
    """For every season and team: in each game, how the team's fantasy points split between the players who played
    (the game's top 3 = key, 4-8 = rotation, 9+ = bench), averaged over the team's games. No games minimum:
    whoever played that night counts. Teams are the teams of that season."""
    files = {2023: DATA / "player_game_logs_regular_2023_24.csv", 2024: DATA / "player_game_logs_regular_2024_25.csv",
             2025: DATA / "player_game_logs_regular.csv", PRESEASON: PRESEASON_LOGS, CURRENT: CURRENT_LOGS}
    out = {}
    for season, f in files.items():
        if not f.exists() or f.stat().st_size < 200:
            continue
        df = pd.read_csv(f, usecols=["TEAM_ABBREVIATION", "GAME_ID", "PLAYER_NAME", "MIN", *DIST_FP])
        df = df[df["MIN"] > 0].copy()
        if df.empty:
            continue
        df["FP"] = sum(df[c] * w for c, w in DIST_FP.items()).clip(lower=0)
        game = df.groupby(["TEAM_ABBREVIATION", "GAME_ID"])["FP"]
        df["total"] = game.transform("sum")
        df = df[df["total"] > 0].copy()
        df["rank"] = game.rank(method="first", ascending=False).loc[df.index]
        df["share"] = df["FP"] / df["total"]
        df["role"] = pd.cut(df["rank"], [0, 3, 8, 1000], labels=["key", "rot", "bench"])
        per_game = df.groupby(["TEAM_ABBREVIATION", "GAME_ID", "role"], observed=False)["share"].sum().unstack(fill_value=0)
        mean = per_game.groupby(level=0).mean()
        games = per_game.groupby(level=0).size()
        top = (df.groupby(["TEAM_ABBREVIATION", "PLAYER_NAME"])["FP"].sum().sort_values(ascending=False)
               .groupby(level=0).head(3).reset_index().groupby("TEAM_ABBREVIATION")["PLAYER_NAME"].apply(list))
        out[str(season)] = {t: [int(games[t]), round(float(r.key), 4), round(float(r.rot), 4), round(float(r.bench), 4),
                                ", ".join(top.get(t, []))] for t, r in mean.iterrows()}
    print(f"Team distribution from game logs: {', '.join(f'{k}: {len(v)} teams' for k, v in out.items())}")
    return out


def team_logos() -> dict:
    """The 30 team logos (team_logos.py), embedded as data URIs: artifacts cannot load outside images."""
    folder = DATA / "team_logos"
    if not folder.exists():
        return {}
    out = {f.stem: "data:image/svg+xml;base64," + base64.b64encode(f.read_bytes()).decode() for f in sorted(folder.glob("*.svg"))}
    league = folder / "NBA.svg"
    if league.exists():  # the NBA wordmark is white: a navy-lettered copy for light backgrounds
        dark = league.read_text(encoding="utf-8").replace('fill="#fffffe"', 'fill="#17223b"', 1)
        out["NBA_light"] = "data:image/svg+xml;base64," + base64.b64encode(dark.encode()).decode()
    return out


FORM_DAYS = [7, 14, 30]


TAU_CATS = ["PTS", "REB", "AST", "STL", "BLK", "FG3M", "FG_PCT", "FT_PCT", "TOV"]


def attach_week_noise(players: list[dict]) -> None:
    """Week-to-week noise for the weekly-noise score: for every player and season, how much his per-game average
    jumps from one week to the next in each category (the variance of his weekly averages; FG% / FT% as impact =
    makes - league% x attempts). p["tau"] = {"2025": [9 variances], ...}; the page averages it over the pool."""
    files = {y: DATA / f"player_game_logs_regular{SEASON_TAG[y]}.csv" for y in AVAIL_SEASONS}
    if CURRENT_LOGS.exists() and CURRENT_LOGS.stat().st_size > 200:
        files[CURRENT] = CURRENT_LOGS
    by_id = {p["id"]: p for p in players}
    for y, f in files.items():
        if not f.exists():
            continue
        d = pd.read_csv(f, usecols=["PLAYER_ID", "GAME_DATE", "MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV",
                                    "FGM", "FGA", "FTM", "FTA"])
        d = d[d["MIN"] > 0].copy()
        d["WEEK"] = (pd.to_datetime(d["GAME_DATE"].astype(str).str[:10]) - pd.to_datetime(d["GAME_DATE"].astype(str).str[:10]).min()).dt.days // 7
        fg, ft = d["FGM"].sum() / d["FGA"].sum(), d["FTM"].sum() / d["FTA"].sum()
        w = d.groupby(["PLAYER_ID", "WEEK"]).mean(numeric_only=True)
        w["FG_PCT"] = w["FGM"] - fg * w["FGA"]
        w["FT_PCT"] = w["FTM"] - ft * w["FTA"]
        g = w.groupby(level=0)
        var = g[TAU_CATS].var()
        var = var[g.size() >= 4]
        for pid, row in var.iterrows():
            if pid in by_id:
                by_id[pid].setdefault("tau", {})[str(y)] = [round(float(v), 4) for v in row.values]
    print(f"Week-to-week noise for {sum(1 for p in players if 'tau' in p)} players")


def attach_form(players: list[dict]) -> str | None:
    """Recent form: each player's averages over the last 7 / 14 / 30 days of regular-season games, counted back from
    the latest game played (the 2026-27 regular season once it starts, before that the end of 2025-26).
    p["form"] = {"7": [games, [STATS averages]], ...}. Returns the last game date."""
    cur = pd.read_csv(CURRENT_LOGS) if CURRENT_LOGS.exists() and CURRENT_LOGS.stat().st_size > 200 else pd.DataFrame()
    logs = cur if not cur.empty else pd.read_csv(DATA / "player_game_logs_regular.csv")
    logs = logs[logs["MIN"] > 0].copy()
    logs["GAME_DATE"] = pd.to_datetime(logs["GAME_DATE"].astype(str).str[:10])
    end = logs["GAME_DATE"].max()
    by_id = {p["id"]: p for p in players}
    ag = adv_games()
    logs["GAME_ID"] = logs["GAME_ID"].astype(str).str.zfill(10)
    for days in FORM_DAYS:
        win = logs[logs["GAME_DATE"] > end - pd.Timedelta(days=days)]
        g = win.groupby("PLAYER_ID")
        means, counts = g[STATS].mean(), g.size()
        adv = adv_over(ag.merge(win[["PLAYER_ID", "GAME_ID"]], on=["PLAYER_ID", "GAME_ID"]), ["PLAYER_ID"])
        for pid, row in means.iterrows():
            if pid in by_id:
                f = [int(counts[pid]), [round(float(row[c]), 2) for c in STATS]]
                if pid in adv:
                    f.append(adv[pid])
                by_id[pid].setdefault("form", {})[str(days)] = f
    print(f"Recent form up to {end:%Y-%m-%d}: {sum(1 for p in players if 'form' in p)} players")
    return f"{end:%Y-%m-%d}"


RECENT_GAMES = 30  # games in the player card


def attach_recent(players: list[dict]) -> None:
    """Each player's last RECENT_GAMES team games (2025-26 regular season, then 2026-27 preseason and regular season),
    games he sat out included: [date, opponent, home 1/0, team pts, opp pts, MIN, PTS, FGM, FGA, FTM, FTA, 3PM, 3PA,
    REB, AST, STL, BLK, TOV], or [date, opponent, home, team pts, opp pts] for a game he did not play."""
    cols = ["PLAYER_ID", "TEAM_ABBREVIATION", "GAME_ID", "GAME_DATE", "MATCHUP", "MIN", "PTS", "FGM", "FGA", "FTM", "FTA",
            "FG3M", "FG3A", "REB", "AST", "STL", "BLK", "TOV"]
    frames = [pd.read_csv(f, usecols=cols, dtype={"GAME_ID": str}) for f in [DATA / "player_game_logs_regular.csv", PRESEASON_LOGS, CURRENT_LOGS]
              if f.exists() and f.stat().st_size > 200]
    logs = pd.concat(frames, ignore_index=True)
    logs["GAME_DATE"] = logs["GAME_DATE"].astype(str).str[:10]
    # one row per team game: date, opponent, home, both scores
    tg = logs.groupby(["GAME_ID", "TEAM_ABBREVIATION"]).agg(date=("GAME_DATE", "first"), matchup=("MATCHUP", "first"), pts=("PTS", "sum")).reset_index()
    tg["opp"] = tg["matchup"].str.split().str[-1]
    tg["home"] = tg["matchup"].str.contains("vs").astype(int)
    opp_pts = tg.set_index(["GAME_ID", "TEAM_ABBREVIATION"])["pts"]
    tg["opp_pts"] = [int(opp_pts.get((g, o), 0)) for g, o in zip(tg["GAME_ID"], tg["opp"])]
    team_games = {t: g.sort_values("date") for t, g in tg.groupby("TEAM_ABBREVIATION")}
    tg_idx = tg.set_index(["GAME_ID", "TEAM_ABBREVIATION"])
    played = logs[logs["MIN"] > 0].sort_values("GAME_DATE")
    by_player = {pid: g for pid, g in played.groupby("PLAYER_ID")}
    for p in players:
        g = by_player.get(p["id"])
        if g is None:
            continue
        rows = {}
        for r in g.itertuples():
            t = tg_idx.loc[(r.GAME_ID, r.TEAM_ABBREVIATION)]
            rows[r.GAME_ID] = [r.GAME_DATE, t.opp, int(t.home), int(t.pts), int(t.opp_pts), round(float(r.MIN)), int(r.PTS), int(r.FGM), int(r.FGA),
                               int(r.FTM), int(r.FTA), int(r.FG3M), int(r.FG3A), int(r.REB), int(r.AST), int(r.STL), int(r.BLK), int(r.TOV)]
        # games his latest team played after he joined it, without him
        last = g.iloc[-1]
        team = last.TEAM_ABBREVIATION
        joined = g[g["TEAM_ABBREVIATION"] == team]["GAME_DATE"].min()
        for t in team_games[team][team_games[team]["date"] >= joined].itertuples():
            if t.GAME_ID not in rows:
                rows[t.GAME_ID] = [t.date, t.opp, int(t.home), int(t.pts), int(t.opp_pts)]
        p["recent"] = sorted(rows.values(), key=lambda x: x[0])[-RECENT_GAMES:][::-1]
    print(f"Recent games for {sum(1 for p in players if 'recent' in p)} players")


BOX_DAYS = 21  # regular-season box scores kept in the page (the whole preseason is small enough)


def box_scores() -> dict:
    """2026-27 box scores by game id: per team, one row per player who played
    [name, player id, MIN, PTS, REB, AST, STL, BLK, 3PM, FGM, FGA, FTM, FTA, TOV, 3PA, starting position or ""].
    Starters first (in the box-score order), then the bench by minutes. Regular season: the last BOX_DAYS days."""
    out = {}
    starters = json.loads(STARTERS.read_text(encoding="utf-8")) if STARTERS.exists() else {}
    for f, recent_only in [(PRESEASON_LOGS, False), (CURRENT_LOGS, True)]:
        if not f.exists() or f.stat().st_size < 200:
            continue
        df = pd.read_csv(f, dtype={"GAME_ID": str})
        df = df[df["MIN"] > 0].copy()
        if df.empty:
            continue
        df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"].astype(str).str[:10])
        if recent_only:
            df = df[df["GAME_DATE"] >= df["GAME_DATE"].max() - pd.Timedelta(days=BOX_DAYS)]
        for (gid, team), g in df.sort_values("MIN", ascending=False).groupby(["GAME_ID", "TEAM_ABBREVIATION"], sort=False):
            gid = str(gid).zfill(10)
            five = starters.get(gid, {})
            order = {pid: i for i, pid in enumerate(five)}
            rows = sorted(g.itertuples(), key=lambda r: order.get(str(int(r.PLAYER_ID)), 99))  # stable: bench keeps minutes order
            out.setdefault(gid, {})[team] = [
                [r.PLAYER_NAME, int(r.PLAYER_ID), round(float(r.MIN)), int(r.PTS), int(r.REB), int(r.AST), int(r.STL), int(r.BLK),
                 int(r.FG3M), int(r.FGM), int(r.FGA), int(r.FTM), int(r.FTA), int(r.TOV), int(r.FG3A),
                 five.get(str(int(r.PLAYER_ID)), "")] for r in rows]
    print(f"Box scores: {len(out)} games")
    return out


def availability(roster: pd.DataFrame) -> dict[int, list]:
    """Games played per season for every player; None for seasons before he reached the NBA,
    0 for a season he was in the league but did not play (a full-season injury)."""
    games, first_season = {}, {}
    for y in range(2014, AVAIL_SEASONS[-1] + 1):
        path = SEASON_FILES / f"all_players_{y}_{(y + 1) % 100:02d}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        for pid, gp in zip(df["PLAYER_ID"], df["GP"]):
            first_season.setdefault(int(pid), y)
            if y in AVAIL_SEASONS:
                games[(int(pid), y)] = int(gp)
    from_year = roster["FROM_YEAR"].dropna().astype(int).to_dict()
    out = {}
    for pid in set(first_season) | set(from_year):
        start = from_year.get(pid, first_season.get(pid))
        out[pid] = [games.get((pid, y), 0) if start is not None and start <= y else None for y in AVAIL_SEASONS]
    return out


def entry(r, roster, adv) -> dict:
    pid = int(r["PLAYER_ID"])
    on_roster = pid in roster.index
    p = {
        "id": pid,
        "name": r["PLAYER_NAME"],
        "age": int(r["AGE"]),
        "team25": r["TEAM_ABBREVIATION"],
        "team26": roster.at[pid, "TEAM_ABBREVIATION"] if on_roster else None,
        "pos": roster.at[pid, "POSITION"] if on_roster else None,
        "gp": int(r["GP"]),
        "s": [round(float(r[c]), 2) for c in STATS],
    }
    if pid in adv.index:
        p["adv"] = [round(float(adv.at[pid, c]), 3) for c in ADV]
    return {k: v if isinstance(v, list) else (None if pd.isna(v) else v) for k, v in p.items()}


def injured_players(current: pd.DataFrame, roster: pd.DataFrame) -> list[dict]:
    """Rostered players with < INJURED_MAX_GP games in 2025-26, using their latest full season."""
    gp_now = current.set_index("PLAYER_ID")["GP"]
    seen, out = set(), []
    for season in PREVIOUS_SEASONS:
        tag = season.replace("-", "_")
        base = pd.read_csv(DATA / f"players_base_pergame_regular_{tag}.csv")
        adv = pd.read_csv(DATA / f"players_advanced_pergame_regular_{tag}.csv").set_index("PLAYER_ID")
        full = base[(base["GP"] >= FULL_SEASON_GP) & (base["MIN"] >= FULL_ROLE_MIN)]
        for _, r in full.iterrows():
            pid = int(r["PLAYER_ID"])
            if pid in seen:
                continue
            seen.add(pid)
            if gp_now.get(pid, 0) >= INJURED_MAX_GP or pid not in roster.index:
                continue
            p = entry(r, roster, adv)
            # team25 is the 2025-26 team, not the team in the older season
            cur = current[current["PLAYER_ID"] == pid]
            p["team25"] = cur["TEAM_ABBREVIATION"].iloc[0] if len(cur) else p["team26"]
            p["src"] = season
            p["team_src"] = r["TEAM_ABBREVIATION"]  # team the shown stats were recorded with
            p["gp_now"] = int(gp_now.get(pid, 0))
            out.append(p)
    return out


def rookies(existing: set[int]) -> list[dict]:
    """2026 draft class with model projections from rookie_projections.py."""
    if not ROOKIE_CSV.exists():
        print(f"{ROOKIE_CSV.name} not found, skipping rookies (run rookie_projections.py)")
        return []
    out = []
    births = json.loads(BIRTHDATES.read_text(encoding="utf-8")) if BIRTHDATES.exists() else {}
    for _, r in pd.read_csv(ROOKIE_CSV).iterrows():
        pid = int(r["PLAYER_ID"])
        if pid in existing:
            continue
        out.append({
            "id": pid,
            "name": r["PLAYER_NAME"],
            # real age today from the birth date (birthdates.py); the projection file only has his last college age
            "age": age_on(births[str(pid)]) if str(pid) in births else None if pd.isna(r["AGE"]) else int(r["AGE"]),
            "team25": None,
            "team26": r["TEAM"],
            "pos": None if pd.isna(r["POSITION"]) else r["POSITION"],
            "gp": int(round(r["GP"])),
            "s": [round(float(r[c]), 2) for c in STATS],
            "rookie": True,
            "seasons": {},
            "pick": int(r["PICK"]),
            "college": None if pd.isna(r["COLLEGE"]) else r["COLLEGE"],
            "note": None if pd.isna(r["SCOUTING_NOTE"]) else r["SCOUTING_NOTE"],
            "pts_range": [round(float(r["PTS_LOW"]), 1), round(float(r["PTS_HIGH"]), 1)],
        })
    return out


def log_lines(path: Path, skip: set[int] = frozenset()) -> dict[int, dict]:
    """Per-game line per player from a game-log file (games he actually played)."""
    if not path.exists() or path.stat().st_size < 100:
        return {}
    logs = pd.read_csv(path)
    logs = logs[(logs["MIN"] > 0) & ~logs["PLAYER_ID"].isin(skip)].sort_values("GAME_DATE")
    # the NBA's advanced numbers for the same games (saved next to the logs by daily_update.py)
    adv_path = path.with_name(path.name.replace("game_logs_", "advanced_"))
    adv = pd.read_csv(adv_path).set_index("PLAYER_ID") if adv_path.exists() and adv_path.stat().st_size > 100 else None
    out = {}
    for pid, g in logs.groupby("PLAYER_ID"):
        line = {"gp": len(g), "t": g["TEAM_ABBREVIATION"].iloc[-1], "s": [round(float(g[c].mean()), 2) for c in STATS]}
        if adv is not None and pid in adv.index and adv.loc[[pid], ADV].notna().all(axis=None):
            line["adv"] = [round(float(adv.at[pid, c]), 3) for c in ADV]
        out[int(pid)] = {"name": g["PLAYER_NAME"].iloc[-1], "line": line}
    return out


def name_key(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def attach_vs(players: list[dict]) -> None:
    """Each player's average over his last VS_GAMES games against every opponent he has faced."""
    frames = [pd.read_csv(f, usecols=["PLAYER_ID", "GAME_ID", "GAME_DATE", "MATCHUP"] + STATS, dtype={"GAME_ID": str})
              for f in GAME_LOG_FILES if f.exists() and f.stat().st_size > 100]
    logs = pd.concat(frames, ignore_index=True)
    logs = logs[logs["MIN"] > 0]
    logs["OPP"] = logs["MATCHUP"].str.split().str[-1]
    logs["GAME_DATE"] = pd.to_datetime(logs["GAME_DATE"].astype(str).str[:10])  # files differ: "2026-10-03" vs "2026-10-03T00:00:00"
    logs = logs.sort_values("GAME_DATE", ascending=False)
    last = logs.groupby(["PLAYER_ID", "OPP"]).head(VS_GAMES)
    agg = last.groupby(["PLAYER_ID", "OPP"]).agg(n=("MIN", "size"), **{c: (c, "mean") for c in STATS}).reset_index()
    by_player: dict[int, dict] = {}
    for r in agg.itertuples(index=False):
        by_player.setdefault(int(r.PLAYER_ID), {})[r.OPP] = [int(r.n)] + [round(float(getattr(r, c)), 1) for c in STATS]
    last = last.assign(GAME_ID=last["GAME_ID"].str.zfill(10))
    adv = adv_over(adv_games().merge(last[["PLAYER_ID", "GAME_ID", "OPP"]], on=["PLAYER_ID", "GAME_ID"]), ["PLAYER_ID", "OPP"])
    for (pid, opp), a in adv.items():
        if pid in by_player and opp in by_player[pid]:
            by_player[pid][opp] = by_player[pid][opp] + a  # [games, STATS..., USG, PACE, ORTG]
    for p in players:
        if p["id"] in by_player:
            p["vs"] = by_player[p["id"]]
    print(f"Head-to-head lines for {sum(1 for p in players if 'vs' in p)} players from {len(logs)} games")


def attach_positions(players: list[dict]) -> None:
    """Fantasy positions (PG / SG / SF / PF / C) from ESPN, matched by name; the NBA's G / F / C as a fallback."""
    espn = {}
    if POSITIONS_CSV.exists():
        espn = {name_key(r.PLAYER_NAME): r.POSITIONS for r in pd.read_csv(POSITIONS_CSV).itertuples(index=False)}
    # players neither ESPN fantasy nor the NBA gives a position: their ESPN player page (positions.py)
    fb_file = HERE / "nba_2026_27" / "positions_fallback.json"
    page = {name_key(k): v for k, v in json.loads(fb_file.read_text(encoding="utf-8")).items()} if fb_file.exists() else {}
    fallback = []
    for p in players:
        pos = espn.get(name_key(p["name"]))
        if pos is None:
            pos = NBA_TO_FANTASY.get(p.get("pos") or "") or NBA_TO_FANTASY.get(page.get(name_key(p["name"]), ""), page.get(name_key(p["name"])))
            fallback.append(p["name"])
        p["pos"] = pos
    print(f"Fantasy positions from ESPN for {len(players) - len(fallback)} players; "
          f"from the NBA position for {len(fallback)}: {', '.join(fallback[:12])}")


def attach_injuries(players: list[dict]) -> None:
    """Mark every player on ESPN's injury list (matched by name) with his status for the badge."""
    if not INJURIES_CSV.exists():
        return
    by_name = {name_key(p["name"]): p for p in players}
    missing = []
    for _, r in pd.read_csv(INJURIES_CSV).iterrows():
        p = by_name.get(name_key(r["PLAYER_NAME"]))
        if p is None:
            missing.append(r["PLAYER_NAME"])
            continue
        clean = lambda v: None if pd.isna(v) else str(v)
        p["hurt"] = {"s": clean(r["FANTASY_STATUS"]) or ("OUT" if r["STATUS"] == "Out" else "GTD"),
                     "inj": clean(r["INJURY"]), "ret": clean(r["RETURN_DATE"]), "note": clean(r["COMMENT"])}
    if missing:
        print(f"Injuries not matched to a player ({len(missing)}): {', '.join(missing[:12])}")


def season_players(roster: pd.DataFrame) -> list[dict]:
    """One record per player with a line for each season he played (per game, plus advanced)."""
    by_id: dict[int, dict] = {}
    for y in AVAIL_SEASONS:
        base = pd.read_csv(DATA / f"players_base_pergame_regular{SEASON_TAG[y]}.csv")
        adv = pd.read_csv(DATA / f"players_advanced_pergame_regular{SEASON_TAG[y]}.csv").set_index("PLAYER_ID")
        for _, r in base[base["GP"] >= SEASON_MIN_GP].iterrows():
            pid = int(r["PLAYER_ID"])
            on_roster = pid in roster.index
            p = by_id.setdefault(pid, {
                "id": pid,
                "team26": roster.at[pid, "TEAM_ABBREVIATION"] if on_roster else None,
                "pos": roster.at[pid, "POSITION"] if on_roster else None,
                "seasons": {},
            })
            p["name"] = r["PLAYER_NAME"]                   # latest spelling wins
            p["age"] = int(r["AGE"]) + (AVAIL_SEASONS[-1] - y)  # age in 2025-26
            line = {"gp": int(r["GP"]), "t": r["TEAM_ABBREVIATION"], "s": [round(float(r[c]), 2) for c in STATS]}
            if pid in adv.index:
                line["adv"] = [round(float(adv.at[pid, c]), 3) for c in ADV]
            p["seasons"][str(y)] = line
    rookie_ids = set(pd.read_csv(ROOKIE_CSV)["PLAYER_ID"].astype(int)) if ROOKIE_CSV.exists() else set()
    # Drafted rookies are their own entries (with a projection), so their 2026-27 lines are added later
    for key, path in [(PRESEASON, PRESEASON_LOGS), (CURRENT, CURRENT_LOGS)]:
        for pid, ln in log_lines(path, rookie_ids).items():
            on_roster = pid in roster.index
            p = by_id.setdefault(pid, {
                "id": pid, "name": ln["name"], "age": None,
                "team26": roster.at[pid, "TEAM_ABBREVIATION"] if on_roster else None,
                "pos": roster.at[pid, "POSITION"] if on_roster else None,
                "seasons": {},
            })
            p["seasons"][str(key)] = ln["line"]
    for p in by_id.values():
        p["team26"] = None if pd.isna(p["team26"]) else p["team26"]
        p["pos"] = None if pd.isna(p["pos"]) else p["pos"]
    return list(by_id.values())


def main() -> None:
    current = pd.read_csv(DATA / "players_base_pergame_regular.csv")
    roster = pd.read_csv(DATA / "player_index_2026_27.csv").set_index("PERSON_ID")

    # Missed most of 2025-26 after a full season before it: drives the "injured" filter and its CSV
    injured = injured_players(current, roster)
    injured_ids = {p["id"] for p in injured}
    players = season_players(roster)
    for p in players:
        p["injured"] = p["id"] in injured_ids
    players += rookies({p["id"] for p in players})
    # Rookies' real 2026-27 regular-season games, used instead of the projection once that season is picked
    current = log_lines(CURRENT_LOGS)
    for p in players:
        if p.get("rookie") and p["id"] in current:
            p["seasons"][str(CURRENT)] = current[p["id"]]["line"]
    cur_max_gp = max((ln["line"]["gp"] for ln in current.values()), default=0)
    seasons = AVAIL_SEASONS + [PRESEASON] + ([CURRENT] if current else [])  # 2026-27 shows up after its first game
    # Free agents are left out; once one signs, the daily roster refresh gives him a team
    free_agents = [p for p in players if not p.get("team26") and not p.get("rookie")]
    players = [p for p in players if p.get("team26") or p.get("rookie")]
    print(f"Left out {len(free_agents)} free agents")
    attach_positions(players)
    attach_injuries(players)
    attach_vs(players)
    attach_recent(players)
    form_end = attach_form(players)
    attach_week_noise(players)
    # Embedded, because claude.ai artifacts cannot load images from other sites
    with_img = 0
    for p in players:
        f = HEADSHOTS / f"{p['id']}.webp"
        if f.exists():
            p["img"] = "data:image/webp;base64," + base64.b64encode(f.read_bytes()).decode()
            with_img += 1
    # birth dates: the page works out each player's age on the day it is opened
    births = json.loads(BIRTHDATES.read_text(encoding="utf-8")) if BIRTHDATES.exists() else {}
    for p in players:
        if str(p["id"]) in births:
            p["born"] = births[str(p["id"])]
    print(f"Birth dates for {sum('born' in p for p in players)} of {len(players)} players")
    site_players = site_images(players)
    print(f"Headshots embedded for {with_img} players")

    pd.DataFrame([{
        "PLAYER_NAME": p["name"], "TEAM_2026_27": p["team26"], "AGE": p["age"],
        "GP_2025_26": p["gp_now"], "LAST_FULL_SEASON": p["src"], "GP": p["gp"],
        **dict(zip(STATS, p["s"])),
        **({"USG_PCT": p["adv"][0], "PACE": p["adv"][1], "OFF_RATING": p["adv"][2]} if p.get("adv") else {}),
    } for p in sorted(injured, key=lambda p: -p["s"][STATS.index("PTS")])]).to_csv(
        INJURED_CSV, index=False, encoding="utf-8-sig")
    print(f"Saved {INJURED_CSV.name} ({len(injured)} players)")

    abbr = roster.drop_duplicates("TEAM_ID").set_index("TEAM_ID")["TEAM_ABBREVIATION"]
    team_seasons = {}
    for y in AVAIL_SEASONS:
        team_adv = pd.read_csv(DATA / f"teams_advanced_pergame_regular{SEASON_TAG[y]}.csv")
        team_seasons[str(y)] = [{"t": abbr.get(r["TEAM_ID"]), "name": r["TEAM_NAME"],
                                 **{c: round(float(r[c]), 2) for c in TEAM_ADV}}
                                for _, r in team_adv.iterrows()]
    # 2026-27 so far (preseason / regular season), from daily_update.py; teams from abroad in the preseason are left out
    for y, tag in [(PRESEASON, "preseason"), (CURRENT, "regular")]:
        f = HERE / "nba_2026_27" / f"teams_advanced_{tag}.csv"
        if f.exists() and f.stat().st_size > 100:
            team_seasons[str(y)] = [{"t": abbr[r["TEAM_ID"]], "name": r["TEAM_NAME"], **{c: round(float(r[c]), 2) for c in TEAM_ADV}}
                                    for _, r in pd.read_csv(f).iterrows() if r["TEAM_ID"] in abbr.index]

    html = TEMPLATE.read_text(encoding="utf-8")
    avail = availability(roster)
    for p in players:
        p["avail"] = avail.get(p["id"], [None] * len(AVAIL_SEASONS))

    inj_updated = INJURIES_STAMP.read_text(encoding="utf-8").strip() if INJURIES_STAMP.exists() else None
    # 2026-27 schedule for the weekly games line: [UTC tip-off, home, away, preseason?]
    sched_df = pd.read_csv(DATA / "schedule_2026_27.csv", low_memory=False,
                           usecols=["gameId", "gameDateTimeUTC", "homeTeam_teamTricode", "awayTeam_teamTricode",
                                    "gameStatus", "homeTeam_score", "awayTeam_score"])
    # [UTC tip-off, home, away, preseason?, game id, final? (1/0), home score, away score]
    sched = [[r.gameDateTimeUTC, r.homeTeam_teamTricode, r.awayTeam_teamTricode, int(str(r.gameId).zfill(10)[2] == "1"),
              str(r.gameId).zfill(10), int(r.gameStatus == 3),
              int(r.homeTeam_score) if r.gameStatus == 3 else None, int(r.awayTeam_score) if r.gameStatus == 3 else None]
             for r in sched_df.itertuples() if isinstance(r.homeTeam_teamTricode, str)]
    payload = json.dumps({"stats": STATS, "seasons": seasons, "preseason": PRESEASON, "current": CURRENT,
                          "curMaxGp": cur_max_gp, "players": players,
                          "teamSeasons": team_seasons, "injUpdated": inj_updated, "vsGames": VS_GAMES, "sched": sched,
                          "dist": team_distribution(), "box": box_scores(), "logos": team_logos(), "formEnd": form_end},
                         ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(html.replace("/*__DATA__*/null", payload), encoding="utf-8")
    # The website loads the photos as separate files (cached, fetched when shown), so the page itself is small
    as_json = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
    build_site(html.replace("/*__DATA__*/null", payload.replace(as_json(players), as_json(site_players), 1)))
    print(f"Saved {OUT.name} ({len(players)} players)")


SITE_IMG = SITE_OUT.parent / "img"
# Visit counting for the website only (roigreen.goatcounter: account "dagger"); the claude.ai copy is private
GOATCOUNTER = '<script data-goatcounter="https://dagger.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>'


def site_images(players: list[dict]) -> list[dict]:
    """Copies of the players for the website: each photo becomes docs/img/<id>.webp instead of inline data."""
    SITE_IMG.mkdir(parents=True, exist_ok=True)
    out = []
    for p in players:
        f = HEADSHOTS / f"{p['id']}.webp"
        if p.get("img") and f.exists():
            dst = SITE_IMG / f.name
            if not dst.exists() or dst.read_bytes() != f.read_bytes():
                dst.write_bytes(f.read_bytes())
            p = {**p, "img": f"img/{f.name}"}
        out.append(p)
    return out


def build_site(html: str) -> None:
    """Wrap the page in a full HTML document and switch it to Supabase sign-in."""
    if not SITE_CONFIG.exists():
        print(f"{SITE_CONFIG.name} not found, skipping the website")
        return
    cfg = json.loads(SITE_CONFIG.read_text(encoding="utf-8"))
    if not cfg.get("supabaseUrl") or not cfg.get("supabaseKey"):
        print(f"{SITE_CONFIG.name} is missing supabaseUrl / supabaseKey, skipping the website")
        return
    # The sign-in library is loaded by the page itself once it is drawn (connectSite)
    site_cfg = json.dumps({"supabaseUrl": cfg["supabaseUrl"], "supabaseKey": cfg["supabaseKey"], "supabaseJs": SUPABASE_JS})
    html = html.replace("/*__SITE__*/null", site_cfg)
    # The template starts with <title>, font links and <style>; those belong in <head>
    cut = html.index("</style>") + len("</style>")
    head, body = html[:cut], html[cut:]
    page = ('<!doctype html><html lang="he"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f"<style>{SITE_RESET}</style>{GOATCOUNTER}{head}</head><body>{body}</body></html>")
    SITE_OUT.parent.mkdir(exist_ok=True)
    SITE_OUT.write_text(page, encoding="utf-8")
    (SITE_OUT.parent / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is
    print(f"Saved website {SITE_OUT.relative_to(HERE)}")


if __name__ == "__main__":
    main()
