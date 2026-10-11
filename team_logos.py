"""
Team logos for the games bar and the game window, from the NBA's image CDN.

    python team_logos.py

Saves ./nba_2025_26/team_logos/<TRICODE>.svg for the 30 teams (skips files already there).
The build embeds them in the page, because claude.ai artifacts cannot load outside images.
"""

import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "nba_2025_26" / "team_logos"
URL = "https://cdn.nba.com/logos/nba/{}/primary/L/logo.svg"
TEAM_IDS = {
    "ATL": 1610612737, "BOS": 1610612738, "BKN": 1610612751, "CHA": 1610612766, "CHI": 1610612741, "CLE": 1610612739,
    "DAL": 1610612742, "DEN": 1610612743, "DET": 1610612765, "GSW": 1610612744, "HOU": 1610612745, "IND": 1610612754,
    "LAC": 1610612746, "LAL": 1610612747, "MEM": 1610612763, "MIA": 1610612748, "MIL": 1610612749, "MIN": 1610612750,
    "NOP": 1610612740, "NYK": 1610612752, "OKC": 1610612760, "ORL": 1610612753, "PHI": 1610612755, "PHX": 1610612756,
    "POR": 1610612757, "SAC": 1610612758, "SAS": 1610612759, "TOR": 1610612761, "UTA": 1610612762, "WAS": 1610612764,
}


def ensure_team_logos() -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    got = failed = 0
    for tri, tid in TEAM_IDS.items():
        f = OUT / f"{tri}.svg"
        if f.exists():
            continue
        try:
            req = urllib.request.Request(URL.format(tid), headers={"User-Agent": "Mozilla/5.0"})
            f.write_bytes(urllib.request.urlopen(req, timeout=30).read())
            got += 1
        except Exception:  # noqa: BLE001 - a missing logo falls back to the team's colours
            failed += 1
        time.sleep(0.05)
    # league logos: the wordmark for the games bar, the upright Logoman for the League Average row
    for name, url in [("NBA", "https://cdn.nba.com/logos/leagues/logo-nba.svg"), ("NBA_mark", "https://cdn.nba.com/logos/leagues/logo-nba-logoman.svg")]:
        if (OUT / f"{name}.svg").exists():
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            (OUT / f"{name}.svg").write_bytes(urllib.request.urlopen(req, timeout=30).read())
        except Exception:  # noqa: BLE001
            pass
    return f"Team logos: {got} new, {failed} unavailable, {len(list(OUT.glob('*.svg')))} cached"


if __name__ == "__main__":
    print(ensure_team_logos())
