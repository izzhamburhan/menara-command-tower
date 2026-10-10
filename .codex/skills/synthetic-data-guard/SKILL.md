---
name: synthetic-data-guard
description: Use when a Menara change touches seed data, scenario files, responses carrying subscriber or location data, UI copy, or anything that could read as a claim about real TM systems. Keeps all data synthetic, labelled, and PDPA-minded.
---

# Synthetic Data Guard

This project is a hackathon demo. Everything is synthetic, and it must be obvious and safe.

## Synthetic and labelled

- All data comes from the seeded generator and `data/scenario/*.yaml`. No real network, customer, ticket, or tower data, and no scraped data.
- Every tool response carries `synthetic: true`. Seeded names say so where natural (for example "(synthetic)" in site names).
- Any UI or generated text shows that the data is synthetic.

## No claims about real TM

- Do not state or imply facts about TM's real systems, prices, coverage, vendors, or practices unless the developer provided them. Ideas in the brief about under-used data are hypotheses, not facts.
- Vendors and firmware in the seed are fictional (`Vendor-A`, `fw-4.2.1`). Place names may be real geography; the events there are fictional.
- No real organisation's branding, logos, or names used to look official. Use generic or clearly fictional branding.

## Privacy by design (PDPA)

- Subscribers are identified only by `msisdn_hash` (`menara_core.privacy.hash_msisdn`). Raw numbers are never stored, logged, or returned, and never appear in tests.
- Location is cell-level at most (`coarsen_location`). Never expose individual tracking.
- Aggregates below `MIN_AGGREGATE_COUNT` (5) are suppressed (`suppress_small`).
- Ticket free text must not contain real personal details. Seeded summaries are generic.
- Secrets (`MENARA_PII_SALT`, `MENARA_SIGNING_KEY`) come from the environment. The dev defaults are for synthetic data only. Never commit `.env`.

## Checks

1. Search the diff for phone-number patterns, emails, real names, and real IDs.
2. Confirm new response fields cannot identify a person; if one could, remove or mask it.
3. Confirm new seed or scenario content is generated or invented, and labelled where shown.
4. Confirm no new text asserts something about TM's real systems.

## Common mistakes

- Putting a "realistic" real phone number or address in a test.
- Returning lat/lng of a subscriber instead of the serving cell's.
- A demo caption written as if the numbers were real TM figures.
