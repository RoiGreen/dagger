"""
Daily pull of 2026-27 game logs: every player's box score from every game played so far.

    python daily_update.py

Writes ./nba_2026_27/ :
  game_logs_preseason.csv   one row per player per game (preseason)
  game_logs_regular.csv     same for the regular season (empty until opening night)
  advanced_<type>.csv       the NBA's advanced per-game numbers (USG%, pace, offensive rating)
  game_logs_advanced_<type>.csv  the same, one row per player per game
  injuries.csv              ESPN injury list (status, injury, expected return)
  positions_espn.csv        ESPN fantasy positions (PG / SG / SF / PF / C)
  starters.json             starting five of every game
Also refreshes ../nba_2025_26/player_index_2026_27.csv (current rosters).
  last_update.txt           when the pull ran and the latest game date in each file

Each run re-downloads the whole season so far, so a missed day fills itself in and nothing
is ever counted twice. Source: stats.nba.com (the same official feed as the rest of the project).
"""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import leaguedashplayerstats, leaguedashteamstats, playergamelogs, playerindex, scheduleleaguev2

from headshots import ensure_headshots
from injuries import pull_injuries
from positions import pull_positions
from starters import pull_starters
from birthdates import pull_birthdates
from team_logos import ensure_team_logos
from nba_stats_2025_26 import fetch

HERE = Path(__file__).parent
OUT = HERE / "nba_2026_27"
SEASON = "2026-27"
SEASON_TYPES = {"Pre Season": "preseason", "Regular Season": "regular"}
KEEP = ["SEASON_YEAR", "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_ABBREVIATION", "GAME_ID", "GAME_DATE",
        "MATCHUP", "WL", "MIN", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", "REB", "AST",
        "TOV", "STL", "BLK", "PF", "PTS", "PLUS_MINUS"]
ADV_GAME_COLS = ["PLAYER_ID", "GAME_ID", "GAME_DATE", "MIN", "POSS", "USG_PCT", "PACE", "OFF_RATING"]


def pull(season_type: str) -> pd.DataFrame:
    df = fetch(playergamelogs.PlayerGameLogs, season_nullable=SEASON, season_type_nullable=season_type)
    if df.empty:
        return pd.DataFrame(columns=KEEP)
    df = df[KEEP].copy()
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"]).dt.date
    return df.sort_values(["GAME_DATE", "GAME_ID", "TEAM_ABBREVIATION", "PLAYER_NAME"])


def pull_advanced(season_type: str, games_path: Path) -> pd.DataFrame:
    """USG%, pace and offensive rating per player. The NBA's season table leaves out players no longer on a
    roster, so they get the same numbers from their per-game advanced lines (weighted by possessions / minutes;
    within 0.1 of the season table for everyone else)."""
    cols = ["PLAYER_ID", "USG_PCT", "PACE", "OFF_RATING"]
    season = fetch(leaguedashplayerstats.LeagueDashPlayerStats, season=SEASON, season_type_all_star=season_type,
                   measure_type_detailed_defense="Advanced", per_mode_detailed="PerGame")
    season = season[cols].assign(FROM_LOGS=False) if not season.empty else pd.DataFrame(columns=cols + ["FROM_LOGS"])
    g = fetch(playergamelogs.PlayerGameLogs, season_nullable=SEASON, season_type_nullable=season_type,
              measure_type_player_game_logs_nullable="Advanced")
    if not g.empty:  # per game too: recent form and head-to-head lines get their advanced numbers from these
        g[ADV_GAME_COLS].to_csv(games_path, index=False, encoding="utf-8-sig")
    g = g[(g["MIN"] > 0) & ~g["PLAYER_ID"].isin(season["PLAYER_ID"])] if not g.empty else g
    if g.empty:
        return season
    by = g.groupby("PLAYER_ID")
    wavg = lambda c, w: (g[c] * g[w]).groupby(g["PLAYER_ID"]).sum() / by[w].sum().replace(0, float("nan"))
    rest = pd.DataFrame({"USG_PCT": wavg("USG_PCT", "POSS"), "PACE": wavg("PACE", "MIN"),
                         "OFF_RATING": wavg("OFF_RATING", "POSS")}).reset_index().assign(FROM_LOGS=True)
    return pd.concat([season, rest], ignore_index=True)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    lines = [f"Pulled {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"]
    # Current rosters, so a free agent who signs shows up with his new team the next morning
    roster = fetch(playerindex.PlayerIndex, season=SEASON)
    roster.to_csv(HERE / "nba_2025_26" / "player_index_2026_27.csv", index=False, encoding="utf-8-sig")
    msg = f"Rosters: {roster['TEAM_ABBREVIATION'].notna().sum()} players on a 2026-27 team"
    print(msg)
    lines.append(msg)
    sched = fetch(scheduleleaguev2.ScheduleLeagueV2, season=SEASON)
    sched.to_csv(HERE / "nba_2025_26" / "schedule_2026_27.csv", index=False, encoding="utf-8-sig")
    msg = f"Schedule: {len(sched)} games"
    print(msg)
    lines.append(msg)
    msg = ensure_headshots(roster["PERSON_ID"])
    print(msg)
    lines.append(msg)
    msg = pull_injuries()
    print(msg)
    lines.append(msg)
    msg = pull_positions()
    print(msg)
    lines.append(msg)
    msg = ensure_team_logos()
    print(msg)
    lines.append(msg)
    for season_type, tag in SEASON_TYPES.items():
        df = pull(season_type)
        path = OUT / f"game_logs_{tag}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        if df.empty:
            msg = f"{season_type}: no games yet"
        else:
            last = df["GAME_DATE"].max()
            msg = (f"{season_type}: {df['GAME_ID'].nunique()} games, {len(df)} player lines, "
                   f"{df['GAME_DATE'].min()} to {last} "
                   f"({df.loc[df['GAME_DATE'] == last, 'GAME_ID'].nunique()} games on {last})")
        print(msg)
        lines.append(msg)
        if not df.empty:
            # the NBA's own advanced numbers (usage, pace, offensive rating need on-court data the box score lacks)
            adv = pull_advanced(season_type, OUT / f"game_logs_advanced_{tag}.csv")
            adv.to_csv(OUT / f"advanced_{tag}.csv", index=False, encoding="utf-8-sig")
            teams = fetch(leaguedashteamstats.LeagueDashTeamStats, season=SEASON, season_type_all_star=season_type,
                          measure_type_detailed_defense="Advanced", per_mode_detailed="PerGame")
            teams.to_csv(OUT / f"teams_advanced_{tag}.csv", index=False, encoding="utf-8-sig")
            msg = f"{season_type} advanced: {len(adv)} players ({adv['FROM_LOGS'].sum()} from per-game logs), {len(teams)} teams"
            print(msg)
            lines.append(msg)
    msg = pull_starters()
    print(msg)
    lines.append(msg)
    msg = pull_birthdates()
    print(msg)
    lines.append(msg)
    (OUT / "last_update.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
