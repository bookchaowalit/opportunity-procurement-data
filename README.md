# book-procurement-data

Find buyer requests with vendor qualification and bid requirements.

Status: **local source pilot**, version 0.1.0. One manually invoked official
source now uses the shared local lake runtime; there is no published remote,
scheduler, hosted API, or consumer integration.
The CLI provides a machine-readable JSON contract, validates an explicit export,
and searches synthetic examples. It never falls back from live data to fixtures.

## Users and boundary

For people and small teams discovering procurement and tenders.
Institutional procurement; individual employment and freelance job listings remain job.v1.

Subcategories: rfp, rfq, public-tender, vendor-registration, framework-agreement.

Domain-specific terms: `buyer_type`, `procurement_method`, `bid_security_required`, `vendor_requirements`.
Each record represents one program/offer intake window. A repeat intake receives
a distinct source record ID. Cross-domain packages use `related_records` rather
than copying the same award into several products.

## Run locally

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
book-procurement-data contract
book-procurement-data demo --open-only
book-procurement-data demo --query "rfp"
book-procurement-data validate src/book_procurement_data/demo.json
python -m unittest discover -s tests -v
```

Developer checks (the same commands CI runs in `.github/workflows/ci.yml` on
Python 3.10 and 3.12, plus a `contract`/`validate`/`demo` CLI smoke):

```bash
python -m pip install -e ".[dev]"
ruff check .
python -m pytest -q
```

All tests are offline: source adapters are exercised with inline fixtures, the
capture entry point is only checked for its fail-closed guard, and no test needs
the shared data-lake runtime or network access. `tests/test_policy.py` keeps
`sources.json`, every `source*.json` policy and the bundled schema consistent.

With dependencies already available, use `PYTHONPATH=src python3 -m book_procurement_data`.
`demo` uses the fixed synthetic clock 2026-09-07T00:00:00Z unless `--as-of` is
provided. `--open-only` excludes closed, unknown-deadline, expired, stale (72h
default), and future-checked records. This is an availability filter; it does
not assert personal eligibility, selection probability, or a guaranteed payout.

Contract: `src/book_procurement_data/schema.json` (`procurement.v1`).
Unknown amounts, currencies, eligibility and deadlines remain unknown. Cash,
credit, discount, in-kind benefits and access are different value kinds. Never
sum them as cash income. Queries and validation are read-only and do not persist
provided files. The `live` label requires captured lineage, but validation alone
does not verify that referenced lake objects exist or prove source truth.

## Data ownership and source policy

Owner: bookchaowalit. Public program metadata only; no applications, personal
screening answers, financial credentials, cookies, or private transcripts.
See `sources.json` and `src/book_procurement_data/source-contracts-finder-open-tenders.json`.
The Contracts Finder OCDS search API is reviewed for public read access. The
adapter requests the official `stages=tender&limit=100` slice, then keeps active
tender notices with future closing dates, values and
structured buyer/suitability terms plus the notice's `eligibilityCriteria`
(capped at 400 characters, with e-mails, links and phone numbers redacted), while
dropping public contact details and other source-body fields from the normalized
contract. No bid, account creation
or messaging is performed.

Implemented flow: approved source pull → immutable landing bytes
and checksum → Bronze Parquet and manifest through the shared lake runtime →
versioned read-only contract → consumer pull. Each product owns its source
adapters and lake prefix. Producers never write into another app's database,
CRM, tasks, application tracker, or notification system.

## Official source pilot

Source: [Contracts Finder OCDS search API](https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search),
documented by the UK government's [Open Contracting publication](https://www.gov.uk/government/publications/open-contracting).
The current capture requests tender-stage releases; the parser keeps only
`tag=tender`, `status=active` releases whose tender closing time is later than
the capture time. Explicit `RFP`, `RFQ`, supplier-registration and
framework-agreement markers in the notice title, method or framework field are
classified into their matching subcategory; all other notices remain
`public-tender`. The latest live pilot captured 65 currently open notices,
including RFQ and framework-agreement examples, buyer,
procurement method, future deadline, suitability flags and any published tender
value. Supplier qualification and portal instructions remain notice-specific.

Run with the existing data-lake Python environment:

```bash
export SOLO_DATA_LAKE_ROOT=/path/to/solo-data-lake
PYTHONPATH=src "$SOLO_DATA_LAKE_ROOT/.venv/bin/python" -m book_procurement_data.capture acquire --lake "$PWD/data/lake" --state-dir "$PWD/data/control"
PYTHONPATH=src "$SOLO_DATA_LAKE_ROOT/.venv/bin/python" -m book_procurement_data.capture records --lake "$PWD/data/lake" --state-dir "$PWD/data/control"
```

The lane depends on the explicit local `discovery.capture_runtime` v1. Capture
is manual, rate-limited to one check per six hours, and rejects sensitive source
markers before archival. A failed latest fetch has no fixture fallback; parser
failures leave a quarantined capture reference. Raw source bytes remain in the
private local lake; normalized output contains no contact email or phone field.
The API response exposes a `links.next` cursor, but this pilot intentionally
captures one bounded 100-release page per six-hour window. Missing `rfp` or
`vendor-registration` in the latest page is therefore an availability gap for
this capture, not a claim that the wider Contracts Finder catalogue has none.

## Next implementation gates

1. Capture a current notice with each remaining explicit `rfp` and
   `vendor-registration` marker before marking those categories observed-live;
   deterministic parser fixtures cover all four markers. The tender-stage query
   keeps active RFQ/framework notices from being hidden by unrelated award
   releases.
2. Add live source tests, retention/access controls and runtime monitoring.
3. Connect a read-only consumer. Personal eligibility, ranking, deadlines and
   application workflow belong to consumers with separate private storage.

No runtime port is reserved. The former `opportunity.v1` is archival; `job.v1` remains a separate job-data contract.
Breaking contract changes require a new version and a consumer migration.
There is no production deployment to roll back; discard demo output or restore
the previous contract version locally. Source permission, live availability,
lake replay and real eligibility are **unverified**, not passing gates.

## Development

```bash
uv sync --frozen --all-extras && uv run mypy  # locked env (uv.lock) as CI installs it
uv run pytest -q --cov
```
