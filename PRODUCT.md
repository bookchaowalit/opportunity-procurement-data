---
title: Procurement and tenders Data Product Charter
status: local-source-pilot
created: 2026-08-08
updated: 2026-10-22
tags: [template, data-engineering, data-product, governance]
description: Outcome, consumers, ownership, contract, quality, privacy, and operating boundary for a data product.
---

# Data Product Charter

## Document control

| Field | Value |
|---|---|
| Data product ID/version | book-procurement-data / procurement.v1 |
| Product owner | bookchaowalit |
| Data owner/steward | bookchaowalit |
| Producer team | Domain repository |
| Status/review date | Local source pilot / 2026-09-07 |
| Evidence boundary | schema.json, demo.json, source policy, capture adapter and tests in this repository |

## Runtime status (verified 2026-10-22)

| What | Status |
|---|---|
| Capture entry point | `python -m book_procurement_data.capture acquire|records|status` (needs `SOLO_DATA_LAKE_ROOT`, the shared `discovery.capture_runtime` v1 in data-lake-pipelines) |
| Who calls it | data-lake-pipelines `infra/scripts/discovery/portfolio.py acquire` for the 1 enabled source IDs in `systems/architecture/discovery-portfolio-v1.json`; that portfolio is wired to a 6-hourly Windows task (`setup_windows_task.ps1`). Whether the task is installed and running is **not verified** from this repo (owner decision D6 on the schedule host is open) [ต้องยืนยัน] |
| Hosted deployment | None. No port, no API, no cloud job |
| Error reporting | Sentry, opt-in: install the `sentry` extra and set `SENTRY_DSN`; a capture run that exits non-zero sends one event tagged `source_id` (no payload, no PII). No DSN is configured for this product yet [ต้องยืนยัน] |
| Contract | `book_procurement_data` `schema.json` (v1 demo) and `schema-v2.json` (captured records); domain-owned, not part of the frozen `data-product-contracts-v2.yaml` port map (the old `opportunity.v1` synthesis is retired, BOO-248) |
| Quality gates in CI | ruff, ruff format, mypy (gradual, see pyproject), offline pytest with coverage ≥ 93%, CLI smoke on Python 3.10 and 3.13, shared security scan |

## Product contract

- Decision or user outcome: Find buyer requests with vendor qualification and bid requirements.
- Consumers and use cases: Discovery applications; integration planned.
- Source systems and lake layers: Contracts Finder OCDS search API → landing → Bronze; synthetic fixtures remain for offline contract tests.
- In scope/out of scope: Institutional procurement; individual employment and freelance job listings remain job.v1.
- Freshness, availability, and volume expectation: Source capture is manually reviewed no more than once per six hours; only active notices with future closing dates are emitted; explicit RFP/RFQ/vendor-registration/framework-agreement markers are classified deterministically and all other notices remain public-tender; open filter rejects checks older than 72h; no live SLA.
- Data classification, residency, retention, and access: Public tender metadata; raw bytes stay in the private local operational lake; normalized output excludes contact email, phone and application payloads.
- Quality thresholds and incident route: All contract tests pass; live quality/replay gates pending; owner handles source failures.
- Cost/capacity guardrail: Offline only, zero provider calls; max 10,000 records per envelope.
- Versioning, deprecation, and migration policy: Draft v1; breaking changes version separately; no legacy migration or live consumer yet.

## Acceptance and ownership

| Gate | Evidence | Owner | Result/status |
|---|---|---|---|
| Contract | Versioned schema and compatibility rules | bookchaowalit | Passed locally |
| Quality | Checks and threshold report | bookchaowalit | Contract and source tests pass |
| Lineage | Source-to-consumer map | bookchaowalit | Captured landing/Bronze lineage verified |
| Access/privacy | Classification and access review | bookchaowalit | Public read; normalized output excludes contacts |
| Operations | Runbook, alert, replay, and recovery | bookchaowalit | Manual capture/replay verified |

## Approval

| Role | Name/date | Decision |
|---|---|---|
| Product/data owner |  | Approve charter / revise |
| Producer owner |  | Accept delivery boundary |
| Consumer representative |  | Accept use and SLA |
