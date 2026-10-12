# NBA Fantasy Draft Room 2026-27

Fantasy basketball draft dashboard built from official NBA stats (stats.nba.com) for the 2025-26 season,
with rookie projections for the 2026 draft class. Each user signs in and keeps their own favorites,
draft picks and settings.

Website: https://roigreen.github.io/dagger/

## How it fits together

| Step | Script | Output |
|---|---|---|
| 1 | `nba_stats_2025_26.py` | Official NBA stats into `nba_2025_26/` |
| 2 | `fetch_rookie_history.py` | Rookie seasons, college seasons (barttorvik.com), team context |
| 3 | `rookie_projections.py` | `rookie_projections_2026_27.csv` (uses `rookie_scouting.csv`) |
| 4 | `team_distribution.py` | `team_distribution.csv`, `team_roles_2026_27.csv` |
| 5 | `build_dashboard.py` | `docs/index.html` (website) and `draft_dashboard.html` (claude.ai version) |

`fantasy_rankings.py` writes a standalone ranking CSV.

## Accounts

Sign-in and per-user data use [Supabase](https://supabase.com). `site_config.json` holds the project URL and
the public anon key (safe to publish; row level security in `supabase_setup.sql` limits each user to their own row).

## Updating

```
pip install nba_api pandas numpy
python nba_stats_2025_26.py
python rookie_projections.py
python team_distribution.py
python build_dashboard.py
git add -A && git commit -m "Update data" && git push
```

GitHub Pages serves `docs/` and refreshes about a minute after a push.
