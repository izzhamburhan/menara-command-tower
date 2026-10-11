# scam-mcp

Where scam calls and messages are spiking, and how many customers a scam shield would protect. **All data is synthetic**: generic patterns (names end in "(synthetic)"), invented counts and invented rates. Track 3 (customer experience), and a candidate paid shield for track 6.

**Counts only.** No phone number, sender, recipient or message text is stored or returned. Patterns carry no real brand, link or number. A pattern with fewer than 5 reports in the window is withheld.

Read-only; owns no tables. Reads `scam_pattern`, `scam_signal`, `tower`, `tower_subscribers`.

## Run

```bash
uv run python -m menara_core.seed.cli                                 # re-seed: the scam tables are new
uv run --package scam-mcp python -m scam_mcp                          # stdio
uv run --package scam-mcp python -m scam_mcp --transport streamable-http --port 8121
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `scam_get_hotspots` | `lat, lng, radius_km=30` (0.1 to 100), `window_min=360` (60 to 1440) | `towns[]`, `patterns[]` ranked by reports: `pattern_id`, `name`, `kind`, `severity`, `reports`, `blocked`, `trend` (`RISING`, `STEADY`, `FALLING`); `total_reports`, `withheld_patterns`, `withheld_reports` |
| `scam_get_pattern` | `pattern_id` (`SCM-01` to `SCM-10`) | `name`, `kind` (`VOICE`, `SMS`, `MESSAGING`), `severity`, `example` (generic wording), `advice` |
| `scam_estimate_protection` | `lat, lng, radius_km=30` | `customers_in_area`, `customers_protected`, `messages_blocked` (last 24 h), `loss_avoided_rm`, `window_hours`, `note` |

Errors: a bad centre, radius or window is `InvalidInputError`; an unknown pattern is `NotFoundError`. An empty circle is not an error: it returns no towns and a warning.

## The model

- Ten generic patterns, hourly report and blocked counts per town from minute -1440 to 720. A few patterns spike in a few towns.
- **Trend** compares the second half of the window with the first: more than 15% up is `RISING`, more than 15% down is `FALLING`.
- **Protection** is an estimate from stated, invented constants: shield adoption 60% of customers, 2% of blocked attempts would have worked, average loss RM 1,800. The answer says it is an estimate.

## Flood scenario

A fake flood-relief donation request surges in the Kelantan towns around T0. For a Kuala Krai circle it leads the list, `RISING` and `HIGH`; a Kuala Lumpur circle does not show it. The care story: warn customers in the flood region with the advice from `scam_get_pattern`.

## Tests

```bash
uv run python -m pytest servers/scam-mcp
```
