"""Capture open Contracts Finder tender notices through the shared lake runtime."""

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

from .cli import resource, timestamp, validate
from .observability import init_sentry, report_exit


def classify_category(tender, title, method):
    """Classify explicit procurement notice markers without guessing from buyer text."""
    title_text = title.casefold()
    method_text = method.casefold()
    combined = f"{title_text} {method_text}"
    if tender.get("frameworkAgreement"):
        return "framework-agreement"
    if re.search(r"\b(?:request\s+for\s+quotation|request\s+for\s+quotes?|rfq)\b", combined):
        return "rfq"
    if re.search(r"\b(?:request\s+for\s+proposals?|rfp)\b", combined):
        return "rfp"
    if re.search(r"\b(?:vendor|supplier)\s+registration\b", combined):
        return "vendor-registration"
    if re.search(r"\bframework\s+agreement\b", combined):
        return "framework-agreement"
    return "public-tender"


def parse_time(value):
    """Parse only RFC3339 timestamps that the published contract also accepts."""
    if not isinstance(value, str):
        return None
    try:
        return timestamp(value)
    except (ValueError, OverflowError):
        return None


def mapping(value):
    """Return a dict for optional OCDS objects that may be absent or null."""
    return value if isinstance(value, dict) else {}


ELIGIBILITY_MAX_CHARS = 400
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_PHONE = re.compile(r"(?:\+|\b0)\d[\d\s()-]{7,}\d")
_TAG = re.compile(r"<[^>]*>")


def eligibility_criteria(tender):
    """Bounded OCDS ``tender.eligibilityCriteria`` text without contact details.

    Markup is stripped, whitespace collapsed, e-mails/URLs/phone numbers redacted
    (the source policy forbids republishing contact bodies) and the text is capped.
    Returns ``None`` when the field is absent, not a string, or empty.
    """
    value = tender.get("eligibilityCriteria")
    if not isinstance(value, str):
        return None
    text = _TAG.sub(" ", value)
    text = _EMAIL.sub("[contact removed]", text)
    text = _URL.sub("[link removed]", text)
    # Phone-like runs (leading + or 0, >= 9 digits); dates and amounts are kept.
    text = _PHONE.sub(lambda m: "[contact removed]" if sum(c.isdigit() for c in m.group()) >= 9 else m.group(), text)
    text = " ".join(text.split())
    if not text:
        return None
    if len(text) > ELIGIBILITY_MAX_CHARS:
        text = text[: ELIGIBILITY_MAX_CHARS - 1].rstrip() + "…"
    return text


def notice_url(release):
    documents = mapping(release.get("tender")).get("documents")
    for document in documents if isinstance(documents, list) else []:
        candidate = mapping(document).get("url")
        if (
            isinstance(candidate, str)
            and candidate.startswith("https://www.contractsfinder.service.gov.uk/Notice/")
            and not any(mark in candidate for mark in ("?", "#"))
        ):
            return candidate
    ocid = quote(release["ocid"], safe="-_.")
    return "https://www.contractsfinder.service.gov.uk/Published/Notice/records/" + ocid + ".json"


def normalize(raw, source, checked_at):
    """Turn an OCDS release package into active public tender metadata."""
    if source["id"] != "contracts-finder-open-tenders":
        raise ValueError("unknown procurement source")
    body = json.loads(raw)
    if (
        not isinstance(body, dict)
        or body.get("version") != "1.1"
        or not isinstance(body.get("releases"), list)
        or not isinstance(body.get("license"), str)
        or "open-government-licence" not in body["license"].casefold()
    ):
        raise ValueError("Contracts Finder source drift or unexpected response")
    observed = parse_time(checked_at)
    if observed is None:
        raise ValueError("invalid capture timestamp")

    items = []
    seen = set()
    for release in body["releases"]:
        if not isinstance(release, dict):
            continue
        tender = release.get("tender")
        tags = release.get("tag")
        if not isinstance(tender, dict) or not isinstance(tags, list) or "tender" not in tags:
            continue
        if tender.get("status") != "active":
            continue
        end_at = mapping(tender.get("tenderPeriod")).get("endDate")
        cutoff = parse_time(end_at)
        if cutoff is None or cutoff <= observed:
            continue
        record_id = release.get("ocid")
        title = tender.get("title")
        buyer = mapping(release.get("buyer")).get("name")
        if not all(isinstance(value, str) and value.strip() for value in (record_id, title, buyer)):
            continue
        if record_id in seen:
            continue
        seen.add(record_id)

        tender_value = mapping(tender.get("value"))
        amount = tender_value.get("amount")
        currency = tender_value.get("currency")
        # json.loads turns NaN/Infinity/1e400 into non-finite floats; drop them
        # (and the currency) rather than publish or crash on a malformed release.
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or not math.isfinite(amount) or amount < 0:
            amount, currency = None, None
        elif not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            amount, currency = None, None

        suitability = mapping(tender.get("suitability"))
        suitability_notes = []
        if isinstance(suitability.get("sme"), bool):
            suitability_notes.append("SME suitability: " + ("yes" if suitability["sme"] else "no"))
        if isinstance(suitability.get("vcse"), bool):
            suitability_notes.append("VCSE suitability: " + ("yes" if suitability["vcse"] else "no"))
        method = tender.get("procurementMethodDetails") or tender.get("procurementMethod") or "Tender method not stated"
        category = tender.get("mainProcurementCategory") or "goods, works or services"
        notice_category = classify_category(tender, title, str(method))
        requirements = (
            "Buyer: " + buyer + "; category: " + str(category) + ". "
            "Review the official notice and its tender portal for supplier qualification, "
            "submission, insurance and delivery requirements. "
            + (
                " ".join(suitability_notes)
                if suitability_notes
                else "Suitability fields are not stated in this release."
            )
        )
        criteria = eligibility_criteria(tender)
        if criteria:
            requirements += " Eligibility criteria (from the notice): " + criteria
        item = {
            "id": record_id,
            "title": title,
            "category": notice_category,
            "source_url": notice_url(release),
            "provider": buyer,
            "status": "open",
            "deadline": {"kind": "fixed", "at": end_at},
            "eligible_countries": [],
            "eligibility_text": (
                "Public UK procurement notice. Supplier eligibility, geographic scope and "
                "portal registration depend on the individual notice; country codes are "
                "left empty rather than inferred from the buyer location."
            ),
            "value": {
                "kind": "cash",
                "amount": amount,
                "currency": currency,
                "guaranteed": False if amount is not None else None,
            },
            "cost": {
                "fee_amount": None,
                "currency": None,
                "auto_renewal": None,
                "notes": "Bid preparation, portal and delivery costs are notice-specific and were not inferred.",
            },
            "terms": {
                "buyer_type": "public",
                "procurement_method": str(method),
                "bid_security_required": None,
                "vendor_requirements": requirements,
            },
            "related_records": [],
            "provenance": {
                "evidence_kind": "captured",
                "source_id": source["id"],
                "source_record_id": record_id,
                "checked_at": checked_at,
                "raw_object_key": None,
                "bronze_manifest_key": None,
            },
        }
        items.append(item)

    return {
        "schema_version": source["schema_version"],
        "source": source["product"],
        "retrieved_at": checked_at,
        "data_status": "live",
        "items": items,
    }


def source_config(source_id=None):
    if source_id is None:
        return resource("source.json")
    if not re.fullmatch(r"[a-z0-9-]+", source_id):
        raise ValueError("invalid source id")
    base = resource("source.json")
    if base["id"] == source_id:
        return base
    try:
        return resource("source-" + source_id + ".json")
    except FileNotFoundError:
        raise ValueError("unknown source id") from None


def main(argv=None):
    selector = argparse.ArgumentParser(add_help=False)
    selector.add_argument("--source-id")
    selected, remaining = selector.parse_known_args(argv)
    root = os.environ.get("SOLO_DATA_LAKE_ROOT")
    if not root:
        print("Set SOLO_DATA_LAKE_ROOT to the local shared capture/lake runtime.", file=sys.stderr)
        return 2
    runtime = Path(root).resolve() / "infra/scripts"
    if not (runtime / "discovery/capture_runtime.py").is_file():
        print("Shared discovery runtime is unavailable.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(runtime))
    from discovery.capture_runtime import VERSION, run

    if VERSION != 1:
        raise RuntimeError("unsupported shared capture runtime")
    source = source_config(selected.source_id)
    sentry = init_sentry(source["id"])
    return report_exit(sentry, source["id"], run(source, normalize, validate, remaining))


if __name__ == "__main__":
    raise SystemExit(main())
