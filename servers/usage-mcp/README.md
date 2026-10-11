# usage-mcp

What people use on the internet, by circle or by tower: the top apps, the category split and the busiest hour. **All data is synthetic**: invented estimates for a demo, not real traffic and not about real people. App names (TikTok, Facebook, Threads and so on) are used only as labels for invented numbers; there are no logos and no claim about any real service.

Read-only; owns no tables. It reads the base tables `tower`, `tower_subscribers`, `app`, `app_hour_factor` and `tower_app_share`, all written by the seed.

Everything is **aggregated**. There is no per-subscriber profile, no hashed subscriber in any answer, and an area with fewer than 5 estimated users is withheld (`withheld: true`, no apps).

## Run

```bash
uv run python -m menara_core.seed.cli                                # re-seed: the usage tables are new
uv run --package usage-mcp python -m usage_mcp                       # stdio
uv run --package usage-mcp python -m usage_mcp --transport streamable-http --port 8113
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `usage_top_apps_in_area` | `lat, lng, radius_km=10` (0.1 to 100), `rank_by="users"` or `"data"`, `hour?` (0 to 23, default the scenario clock's hour), `limit=10` (1 to 20) | `hour`, `towers_counted`, `total_users_est`, `apps[]` ranked (`rank`, `app_id`, `name`, `category`, `users_est`, `reach_pct`, `data_share_pct`), `categories[]` (`category`, `data_share_pct`, sums to 100), `busiest_hour`, `withheld`, `note` |
| `usage_get_tower_apps` | `enodeb_name, rank_by, hour?, limit` | the same for one tower |
| `usage_app_trend` | `lat, lng, app, radius_km=10` (`app` is an app id such as `tiktok` or a name such as `TikTok`) | `points[24]` (`hour`, `users_est`, `reach_pct`), `peak_hour`, `towers_counted`, `total_users_est` |

Errors: out-of-range numbers or an unknown app (the message lists the valid ids) are `InvalidInputError`; an unknown tower is `NotFoundError`. A circle with no towers is not an error: `towers_counted: 0` and a warning.

## The model

- **Catalogue:** 14 apps in 8 categories (short video, social, messaging, video streaming, music, gaming, commerce, mobility).
- **Users in an hour** for an app = the sum over the towers in the circle of (the tower's estimated users) x (the share of them who use the app in a day) x (the share of its daily users online with it in that hour, about 40% at the peak). `reach_pct` is that over all the estimated users in the circle.
- **Data share** weights each app's share of a tower's data by the same hourly activity, then renormalises, so video apps lead on data and messengers lead on users.
- Each town has its own favourite app and a rising one, so different places have a different number one. Evenings are busier than the small hours.

## Flood scenario

Nothing special: the flood does not change usage. Compare a Kuala Krai circle with a Tawau circle to see different leaders.

## Tests

```bash
uv run python -m pytest servers/usage-mcp
```
