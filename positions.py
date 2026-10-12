"""
Pull each player's fantasy positions (PG / SG / SF / PF / C) from ESPN Fantasy into
./nba_2026_27/positions_espn.csv.

    python positions.py

A player is listed under every position he is eligible for in ESPN fantasy lineups (e.g. "PG/SG").
Eligibility grows during the season, so the daily run and the GitHub workflow refresh it.
Needs only pandas; a failed pull keeps the previous file.
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "nba_2026_27"
SEASON = 2027  # ESPN names a season by the year it ends: 2027 = 2026-27
URL = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{SEASON}/players?scoringPeriodId=0&view=players_wl"
SLOTS = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C"}  # ESPN lineup slot ids; 5 = G, 6 = F and the rest are combined slots


def pull_positions() -> str:
    try:
        req = urllib.request.Request(URL, headers={
            "User-Agent": "Mozilla/5.0",
            "X-Fantasy-Filter": json.dumps({"filterActive": {"value": True}}),
        })
        data = json.load(urllib.request.urlopen(req, timeout=60))
    except Exception as e:  # noqa: BLE001
        return f"Positions: pull failed ({e}), kept the previous list"
    rows = []
    for p in data:
        pos = [SLOTS[s] for s in sorted(p.get("eligibleSlots", [])) if s in SLOTS]
        if pos:
            rows.append({"PLAYER_NAME": p["fullName"], "POSITIONS": "/".join(pos)})
    if not rows:
        return "Positions: ESPN returned no players, kept the previous list"
    OUT.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "positions_espn.csv", index=False, encoding="utf-8-sig")
    return f"Positions: {len(rows)} players; " + fill_missing({r["PLAYER_NAME"] for r in rows})


# Fallback for players ESPN fantasy does not list yet (two-way and undrafted rookies), whom the NBA also gives no
# position: the position on their ESPN player page (G / F / C, or PG ... C), asked once per player
FALLBACK = OUT / "positions_fallback.json"
ROSTERS = HERE / "nba_2025_26" / "player_index_2026_27.csv"
NBA_SEARCH = "https://site.web.api.espn.com/apis/common/v3/search?query={q}&limit=5&type=player"
ATHLETE = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}"


def _key(name: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", re.sub(r"(jr|sr|ii|iii|iv)\.?", "", s))


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def fill_missing(espn_names: set) -> str:
    if not ROSTERS.exists():
        return "fallback skipped (no roster file)"
    have = json.loads(FALLBACK.read_text(encoding="utf-8")) if FALLBACK.exists() else {}
    known = {_key(n) for n in espn_names}
    idx = pd.read_csv(ROSTERS)
    idx = idx[idx["TEAM_ABBREVIATION"].notna() & idx["POSITION"].isna()]
    new = 0
    for r in idx.itertuples():
        name = f"{r.PLAYER_FIRST_NAME} {r.PLAYER_LAST_NAME}"
        if _key(name) in known or name in have:
            continue
        try:
            hits = [h for h in _get(NBA_SEARCH.format(q=urllib.parse.quote(name))).get("items", []) if h.get("league") == "nba"]
            if not hits:
                continue
            pos = (_get(ATHLETE.format(id=hits[0]["id"])).get("athlete") or {}).get("position") or {}
            if pos.get("abbreviation"):
                have[name] = pos["abbreviation"]
                new += 1
        except Exception:  # noqa: BLE001
            continue
    FALLBACK.write_text(json.dumps(have, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return f"fallback positions: {len(have)} ({new} new)"


if __name__ == "__main__":
    print(pull_positions())
