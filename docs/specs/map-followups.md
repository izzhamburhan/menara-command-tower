# Spec: three small fixes found by the live map runs

Status: approved by the developer in chat ("Yup"). Additive changes to `user-mcp` responses only; no new tools, tables, ports or seed changes.

## Why

A live DeepSeek run on the map tools (Kuala Krai and Tawau) showed three things a model, or a UI, gets wrong or does inefficiently:

1. It added up per-tower population estimates itself and was about 8% off (26,000 against 28,338).
2. It read the first trail segment as "the start of the day" although it was only the start of the 24-hour window.
3. It called `user_get_trail` six times to find a subscriber who had changed towers.

## Acceptance criteria

1. `SubscriberList.subscribers_est_total` is the sum of `subscribers_est` over `towers[]`. It is `null` when the list is withheld, and 0 for an area with no subscribers. A tower whose estimate is unknown counts as 0 and the response carries a warning.
2. `AreaSubscriber.cell_changes_24h` is the number of cell changes in the 24 hours up to the scenario clock (the subscriber's first-ever visit is not a change). It is 0 for a subscriber who never moves, and it follows the clock for a commuter.
3. `Trail.window_start` is the ISO time the window begins (`clock - window_min`), so a first segment that arrived before it can be read correctly.
4. All existing tests keep passing; the tool descriptions mention the new fields.

## Contract

Only new response fields (`subscribers_est_total`, `cell_changes_24h`, `window_start`) on `user_list_in_area`, `user_list_on_tower` and `user_get_trail`. Existing fields and arguments are unchanged, so existing callers are not affected.

## Privacy

`cell_changes_24h` is a count, derived from the cell-level trail already exposed by `user_get_trail`. It identifies no one beyond the hash that is already listed, and small groups remain withheld as before.

## Rollout

Restart running `user-mcp` servers. No re-seed.