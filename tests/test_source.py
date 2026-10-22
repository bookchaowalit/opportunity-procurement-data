import json
import unittest
from copy import deepcopy

from book_procurement_data.capture import classify_category, normalize
from book_procurement_data.cli import resource, validate


class SourceTests(unittest.TestCase):
    def raw(self):
        return json.dumps(
            {
                "version": "1.1",
                "license": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
                "releases": [
                    {
                        "ocid": "ocds-test-open",
                        "id": "release-open",
                        "tag": ["tender"],
                        "buyer": {"name": "Example Council"},
                        "parties": [{"contactPoint": {"email": "public@example.gov.uk", "telephone": "000"}}],
                        "tender": {
                            "title": "Digital service tender",
                            "status": "active",
                            "mainProcurementCategory": "services",
                            "procurementMethodDetails": "Open procedure",
                            "tenderPeriod": {"endDate": "2026-10-01T12:00:00+01:00"},
                            "value": {"amount": 125000, "currency": "GBP"},
                            "suitability": {"sme": True, "vcse": False},
                            "documents": [{"url": "https://www.contractsfinder.service.gov.uk/Notice/abc"}],
                        },
                    },
                    {
                        "ocid": "ocds-test-award",
                        "id": "release-award",
                        "tag": ["award"],
                        "buyer": {"name": "Example Council"},
                        "tender": {
                            "title": "Closed award",
                            "status": "complete",
                            "tenderPeriod": {"endDate": "2026-09-01T12:00:00+01:00"},
                        },
                    },
                ],
            }
        ).encode("utf-8")

    def test_contracts_finder_source_fixture(self):
        source = resource("source.json")
        data = normalize(self.raw(), source, "2026-09-07T00:00:00Z")
        item = data["items"][0]
        item["provenance"].update(
            raw_object_key="landing/test",
            bronze_manifest_key="control/manifests/test",
        )
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(item["id"], "ocds-test-open")
        self.assertEqual(item["status"], "open")
        self.assertEqual(item["value"], {"kind": "cash", "amount": 125000, "currency": "GBP", "guaranteed": False})
        self.assertIsNone(item["terms"]["bid_security_required"])
        self.assertNotIn("public@example.gov.uk", json.dumps(item))
        self.assertNotIn("telephone", json.dumps(item).lower())
        self.assertEqual(validate(data)["schema_version"], source["schema_version"])

    def test_source_drift_rejected(self):
        with self.assertRaises(ValueError):
            normalize(b'{"version":"1","releases":[]}', resource("source.json"), "2026-09-07T00:00:00Z")

    def test_category_classifier_requires_explicit_markers(self):
        self.assertEqual(resource("source.json")["fetch_query"], {"limit": "100", "stages": "tender"})
        self.assertEqual(
            resource("source.json")["category_capabilities"],
            ["rfp", "rfq", "public-tender", "vendor-registration", "framework-agreement"],
        )
        self.assertEqual(classify_category({}, "Request for Proposals: digital service", "Open procedure"), "rfp")
        self.assertEqual(classify_category({}, "RFQ for office supplies", "Quotation"), "rfq")
        self.assertEqual(
            classify_category({}, "Supplier registration portal", "Dynamic purchasing"), "vendor-registration"
        )
        self.assertEqual(
            classify_category({"frameworkAgreement": {"method": "open"}}, "Services", "Open procedure"),
            "framework-agreement",
        )
        self.assertEqual(classify_category({}, "Digital service tender", "Open procedure"), "public-tender")

    def test_normalize_emits_explicit_categories(self):
        payload = json.loads(self.raw().decode("utf-8"))
        payload["releases"][0]["tender"]["title"] = "Request for Proposals: digital service"
        data = normalize(json.dumps(payload).encode("utf-8"), resource("source.json"), "2026-09-07T00:00:00Z")
        self.assertEqual(data["items"][0]["category"], "rfp")

    def test_normalize_covers_each_adapter_only_category_with_explicit_markers(self):
        source = resource("source.json")
        cases: list[tuple[str, str, str, dict[str, str]]] = [
            ("rfp", "Request for Proposals: digital service", "Open procedure", {}),
            ("rfq", "Request for Quotation: office supplies", "Quotation", {}),
            ("vendor-registration", "Supplier registration portal", "Dynamic purchasing", {}),
            ("framework-agreement", "Design services framework agreement", "Open procedure", {}),
        ]
        releases = []
        for index, (expected, title, method, extra) in enumerate(cases, start=1):
            release = deepcopy(json.loads(self.raw().decode("utf-8"))["releases"][0])
            release["ocid"] = f"ocds-test-{expected}-{index}"
            release["id"] = f"release-{expected}-{index}"
            release["tender"]["title"] = title
            release["tender"]["procurementMethodDetails"] = method
            release["tender"].update(extra)
            releases.append(release)
        payload = {
            "version": "1.1",
            "license": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
            "releases": releases,
        }
        data = normalize(json.dumps(payload).encode("utf-8"), source, "2026-09-07T00:00:00Z")
        self.assertEqual([item["category"] for item in data["items"]], [case[0] for case in cases])

    def test_malformed_releases_are_skipped_not_fatal(self):
        payload = json.loads(self.raw().decode("utf-8"))
        good = payload["releases"][0]
        space_date = deepcopy(good)
        space_date["ocid"] = "ocds-test-space-date"
        space_date["tender"]["tenderPeriod"]["endDate"] = "2026-10-01 12:00:00+01:00"
        naive_date = deepcopy(good)
        naive_date["ocid"] = "ocds-test-naive-date"
        naive_date["tender"]["tenderPeriod"]["endDate"] = "2026-10-01T12:00:00"
        payload["releases"] += [
            space_date,
            naive_date,
            None,
            "not-a-release",
            {"ocid": "ocds-null-tag", "tag": None, "tender": {"status": "active"}},
            {
                "ocid": "ocds-null-parts",
                "tag": ["tender"],
                "buyer": None,
                "tender": {"status": "active", "title": "t", "tenderPeriod": None, "value": None},
            },
        ]
        data = normalize(json.dumps(payload).encode("utf-8"), resource("source.json"), "2026-09-07T00:00:00Z")
        for item in data["items"]:
            item["provenance"].update(raw_object_key="landing/test", bronze_manifest_key="control/manifests/test")
        self.assertEqual([item["id"] for item in data["items"]], ["ocds-test-open"])
        self.assertEqual(validate(data)["data_status"], "live")

    def test_non_finite_amounts_are_dropped_not_published(self):
        for literal in ("NaN", "Infinity", "-Infinity", "1e400"):
            raw = self.raw().decode("utf-8").replace('"amount": 125000', '"amount": ' + literal)
            self.assertIn(literal, raw)
            data = normalize(raw.encode("utf-8"), resource("source.json"), "2026-09-07T00:00:00Z")
            item = data["items"][0]
            item["provenance"].update(raw_object_key="landing/test", bronze_manifest_key="control/manifests/test")
            with self.subTest(literal=literal):
                self.assertEqual(item["value"], {"kind": "cash", "amount": None, "currency": None, "guaranteed": None})
                self.assertEqual(validate(data)["data_status"], "live")

    def test_tender_cutoff_compares_instants_across_offsets(self):
        # endDate 2026-10-01T12:00+01:00 is 11:00 UTC; the notice closes at that instant.
        cases = {
            "2026-10-01T10:59:59Z": 1,
            "2026-10-01T11:00:00Z": 0,
            "2026-10-01T17:59:59+07:00": 1,
            "2026-10-01T18:00:00+07:00": 0,
            "2026-10-01T06:59:59-04:00": 1,
        }
        for checked_at, count in cases.items():
            with self.subTest(checked_at=checked_at):
                self.assertEqual(len(normalize(self.raw(), resource("source.json"), checked_at)["items"]), count)
        with self.assertRaises(ValueError):
            normalize(self.raw(), resource("source.json"), "2026-10-01T10:00:00")

    def test_short_fraction_end_dates_are_kept_on_every_python(self):
        payload = json.loads(self.raw().decode("utf-8"))
        payload["releases"][0]["tender"]["tenderPeriod"]["endDate"] = "2026-10-01T12:00:00.5+01:00"
        data = normalize(json.dumps(payload).encode("utf-8"), resource("source.json"), "2026-09-07T00:00:00Z")
        self.assertEqual([item["deadline"]["at"] for item in data["items"]], ["2026-10-01T12:00:00.5+01:00"])

    def test_null_optional_objects_do_not_crash(self):
        payload = json.loads(self.raw().decode("utf-8"))
        tender = payload["releases"][0]["tender"]
        tender.update(value=None, suitability=None, documents=None)
        payload["releases"][0]["ocid"] = "ocds test/with?odd#chars"
        data = normalize(json.dumps(payload).encode("utf-8"), resource("source.json"), "2026-09-07T00:00:00Z")
        item = data["items"][0]
        item["provenance"].update(raw_object_key="landing/test", bronze_manifest_key="control/manifests/test")
        self.assertEqual(item["value"]["amount"], None)
        self.assertNotIn("?", item["source_url"])
        self.assertNotIn("#", item["source_url"])
        self.assertEqual(validate(data)["schema_version"], "procurement.v1")

    def test_eligibility_criteria_are_mapped_bounded_and_contact_free(self):
        payload = json.loads(self.raw().decode("utf-8"))
        payload["releases"][0]["tender"]["eligibilityCriteria"] = (
            "<p>Suppliers must hold ISO 27001 and Cyber Essentials Plus by 2026-10-01.</p>\n"
            "Minimum turnover £250,000. Questions: bids@example.gov.uk, "
            "call +44 1632 960000 or 01632 960001, see https://portal.example.gov.uk/x?id=1"
        )
        data = normalize(json.dumps(payload).encode("utf-8"), resource("source.json"), "2026-09-07T00:00:00Z")
        item = data["items"][0]
        requirements = item["terms"]["vendor_requirements"]
        self.assertIn("Eligibility criteria (from the notice): Suppliers must hold ISO 27001", requirements)
        self.assertIn("by 2026-10-01", requirements)
        self.assertIn("£250,000", requirements)
        for leaked in ("bids@example.gov.uk", "1632 960000", "01632 960001", "portal.example", "<p>"):
            self.assertNotIn(leaked, requirements)
        item["provenance"].update(raw_object_key="landing/test", bronze_manifest_key="control/manifests/test")
        self.assertEqual(validate(data)["schema_version"], "procurement.v1")

        payload["releases"][0]["tender"]["eligibilityCriteria"] = "x" * 5000
        long_item = normalize(json.dumps(payload).encode("utf-8"), resource("source.json"), "2026-09-07T00:00:00Z")
        criteria = long_item["items"][0]["terms"]["vendor_requirements"].split("(from the notice): ", 1)[1]
        self.assertEqual(len(criteria), 400)
        self.assertTrue(criteria.endswith("…"))

        for absent in (None, 42, "   ", "<br/>"):
            payload["releases"][0]["tender"]["eligibilityCriteria"] = absent
            plain = normalize(json.dumps(payload).encode("utf-8"), resource("source.json"), "2026-09-07T00:00:00Z")
            self.assertNotIn("Eligibility criteria", plain["items"][0]["terms"]["vendor_requirements"])

    def test_non_object_or_unlicensed_body_rejected(self):
        for body in (b"[]", b'{"version":"1.1","releases":[],"license":null}', b'{"version":"1.1","releases":[]}'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                normalize(body, resource("source.json"), "2026-09-07T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
