"""
Player headshots for the dashboard, from the NBA's official image CDN.

    python headshots.py

Downloads the headshot of every player on a 2026-27 roster that is not cached yet, crops it to a
square around the face and saves a 120x120 WebP in ./nba_2025_26/headshots_hd/<player id>.webp
(sharp enough for the big comparison photos; the tables show it smaller).
The build embeds these thumbnails in the page (claude.ai artifacts cannot load outside images).
Run daily by daily_update.py, so new signings get a picture the next morning.
"""

import io
import time
import urllib.request
from pathlib import Path

import pandas as pd
from PIL import Image

HERE = Path(__file__).parent
CACHE = HERE / "nba_2025_26" / "headshots_hd"
ROSTER = HERE / "nba_2025_26" / "player_index_2026_27.csv"
URL = "https://cdn.nba.com/headshots/nba/latest/260x190/{}.png"
SIZE = 120


def thumbnail(png: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    return img.crop((left, 0, left + side, side)).resize((SIZE, SIZE), Image.LANCZOS)


def ensure_headshots(player_ids) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    missing = [int(pid) for pid in player_ids if not (CACHE / f"{int(pid)}.webp").exists()]
    got = failed = 0
    for pid in missing:
        try:
            req = urllib.request.Request(URL.format(pid), headers={"User-Agent": "Mozilla/5.0"})
            png = urllib.request.urlopen(req, timeout=30).read()
            thumbnail(png).save(CACHE / f"{pid}.webp", "WEBP", quality=74)
            got += 1
        except Exception:  # noqa: BLE001 - no picture just means no avatar for that player
            failed += 1
        time.sleep(0.05)
    return f"Headshots: {got} new, {failed} unavailable, {len(list(CACHE.glob('*.webp')))} cached"


if __name__ == "__main__":
    print(ensure_headshots(pd.read_csv(ROSTER)["PERSON_ID"]))
