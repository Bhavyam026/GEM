import unittest
import tempfile
import json
from urllib.parse import parse_qs
from pathlib import Path

from scripts.scan_gem import (
    normalize_bid_number, record_key, dedupe_records,
    buyer_matches, category_for, location_matches, q_tier_for, office_name_for, bid_is_active,
    target_ministry_department, BUYERS, GeMSession, SEARCH_API, ADVANCE_SEARCH, TextOnly,
)
from scripts.pdf_extract import TenderLinks, safe_pdf_filename, save_original_pdf



class AdvanceSearchApiTests(unittest.TestCase):
    def test_exact_organization_payloads_for_all_three_buyers(self):
        expected = {
            "NPCIL": "NUCLEAR POWER CORPORATION OF INDIA LIMITED",
            "BARC": "Bhabha Atomic Research Centre",
            "AEES": "Atomic Energy Education Society (AEES)",
        }
        for buyer, organization in expected.items():
            payload = GeMSession.build_advance_payload(buyer, 1)
            self.assertEqual(payload, {
                "searchType": "ministry-search",
                "ministry": "PMO",
                "buyerState": "",
                "organization": organization,
                "department": "Department of Atomic Energy",
                "bidEndFromMin": "",
                "bidEndToMin": "",
                "page": 1,
            })
            self.assertEqual(BUYERS[buyer]["organization"], organization)

    def test_page_two_uses_same_organization_and_page_number_two(self):
        payload = GeMSession.build_advance_payload("NPCIL", 2)
        self.assertEqual(payload["organization"], "NUCLEAR POWER CORPORATION OF INDIA LIMITED")
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["searchType"], "ministry-search")

    def test_search_posts_form_payload_to_advance_search_endpoint(self):
        session = GeMSession()
        session.csrf = "fresh-session-token"
        captured = {}

        def fake_request(url, data=None, headers=None, attempts=3):
            captured["url"] = url
            captured["form"] = parse_qs(data.decode("utf-8"))
            captured["headers"] = headers
            return json.dumps({
                "code": 200,
                "response": {"response": {
                    "numFound": 448,
                    "start": 10,
                    "docs": [{"b_id": [123]}],
                }},
                "current_page": 1,
            })

        session.request = fake_request
        result = session.search("NPCIL", 2)
        sent_payload = json.loads(captured["form"]["payload"][0])
        self.assertEqual(captured["url"], SEARCH_API)
        self.assertEqual(captured["headers"]["Referer"], ADVANCE_SEARCH)
        self.assertEqual(captured["form"]["csrf_bd_gem_nk"], ["fresh-session-token"])
        self.assertEqual(sent_payload["organization"], "NUCLEAR POWER CORPORATION OF INDIA LIMITED")
        self.assertEqual(sent_payload["page"], 2)
        self.assertEqual(result["total"], 448)
        self.assertEqual(result["start"], 10)
        self.assertEqual(result["current_page"], 1)
        self.assertEqual(len(result["docs"]), 1)

    def test_csrf_is_read_from_fresh_advance_search_html(self):
        session = GeMSession()
        token = "a" * 32
        session.request = lambda *args, **kwargs: (
            '<input type="hidden" name="csrf_bd_gem_nk" value="' + token + '">'
        )
        session.init()
        self.assertEqual(session.csrf, token)


class DeduplicationTests(unittest.TestCase):
    def test_bid_number_normalizes_case_and_whitespace(self):
        self.assertEqual(normalize_bid_number(" gem / 2026 / b / 12345 "), "GEM/2026/B/12345")

    def test_same_bid_number_is_one_record_and_first_seen_is_preserved(self):
        rows = [
            {"bid_number": "GEM/2026/B/12345", "title": "Old title", "first_seen": "2026-11-01"},
            {"bid_number": " gem / 2026 / b / 12345 ", "title": "Updated title", "first_seen": "2026-11-12"},
        ]
        unique = dedupe_records(rows)
        self.assertEqual(len(unique), 1)
        item = next(iter(unique.values()))
        self.assertEqual(item["title"], "Updated title")
        self.assertEqual(item["first_seen"], "2026-11-01")
        self.assertEqual(item["id"], "bid:GEM/2026/B/12345")

    def test_url_is_fallback_identity(self):
        a = {"url": "https://bidplus.gem.gov.in/showbidDocument/123?x=1"}
        b = {"url": "https://BIDPLUS.GEM.GOV.IN/showbidDocument/123#details"}
        self.assertEqual(record_key(a), record_key(b))
        self.assertTrue(record_key(a).startswith("url:"))


class BuyerAndCategoryTests(unittest.TestCase):
    def test_only_exact_buyer_aliases_match(self):
        self.assertTrue(buyer_matches("NPCIL", "Nuclear Power Corporation of India Limited"))
        self.assertTrue(buyer_matches("BARC", "Buyer: BARC"))
        self.assertFalse(buyer_matches("BARC", "Bharat Heavy Electricals Limited"))
        self.assertFalse(buyer_matches("BARC", "", "BARC is mentioned in an unrelated technical specification"))
        self.assertTrue(buyer_matches("AEES", "Atomic Energy Education Society"))

    def test_exact_pmo_and_atomic_energy_scope_is_required(self):
        self.assertTrue(target_ministry_department("PMO", "Department of Atomic Energy"))
        self.assertTrue(target_ministry_department("Prime Minister's Office", "Department of Atomic Energy"))
        self.assertFalse(target_ministry_department("Ministry of Defence", "Department of Atomic Energy"))
        self.assertFalse(target_ministry_department("PMO", "Department of Telecommunications"))

    def test_categories_are_classified_from_bid_text(self):
        self.assertEqual(category_for("Annual Maintenance Contract for CCTV systems"), "CCTV & Surveillance")
        self.assertEqual(category_for("Comprehensive Maintenance Contract for network equipment"), "Networking")
        self.assertEqual(category_for("Supply of IP CCTV cameras"), "CCTV & Surveillance")
        self.assertEqual(category_for("Supply of LAN Switches"), "Networking")
        self.assertEqual(category_for("Facility Management Service; O&M of Electrical Work; Skilled"), "Electrical")
        self.assertEqual(category_for("Fire alarm and smoke detector"), "Fire Safety")
        self.assertEqual(category_for("unrelated stationery"), "")

    def test_office_name_is_separate_from_buyer_organisation(self):
        self.assertEqual(office_name_for("Organisation Name Bhabha Atomic Research Centre Office Name Nrb Contact details"), "Nrb")

    def test_only_explicit_q3_tier_is_accepted(self):
        self.assertEqual(q_tier_for("Q3"), "Q3")
        self.assertEqual(q_tier_for("Category: Q3 - CCTV"), "Q3")
        self.assertEqual(q_tier_for("Q2"), "rejected")
        self.assertEqual(q_tier_for("Q4"), "rejected")
        self.assertEqual(q_tier_for("CCTV camera supply"), "manual_review")
        self.assertEqual(q_tier_for("Q2 and Q3"), "manual_review")

    def test_location_matching_includes_boisar_and_pin_codes(self):
        self.assertEqual(location_matches("Delivery at Tarapur Site, Boisar, Palghar 401504"),
                         ["Palghar", "Boisar"])
        self.assertEqual(location_matches("Mumbai 400094"), ["Mumbai"])
        self.assertEqual(location_matches("Thane 400601"), [])
        self.assertEqual(location_matches("Chennai 600001"), [])


class PdfLinkTests(unittest.TestCase):
    def test_python38_conditional_marked_sections_do_not_crash_text_parser(self):
        parser = TextOnly()
        parser.feed("<![if !IE]><div>Public tender details</div><![endif]>")
        self.assertIn("Public tender details", parser.text())

    def test_python38_conditional_marked_sections_do_not_crash_pdf_link_parser(self):
        parser = TenderLinks("https://bidplus.gem.gov.in/showbidDocument/1")
        parser.feed('<![if !IE]><a href="/download/abc.pdf">Download PDF</a><![endif]>')
        self.assertEqual(parser.links, ["https://bidplus.gem.gov.in/download/abc.pdf"])

    def test_pdf_filename_is_safely_mapped_to_bid_number(self):
        self.assertEqual(safe_pdf_filename("GEM/2026/B/12345"), "GEM_2026_B_12345.pdf")

    def test_original_pdf_bytes_are_saved_unchanged_and_bid_mapped(self):
        original = b"%PDF-1.7\\nOriginal GeM document bytes\\n%%EOF"
        with tempfile.TemporaryDirectory() as tmp:
            relative = save_original_pdf(original, "GEM/2026/B/12345", Path(tmp))
            saved = Path(tmp) / relative.replace("data/", "")
            self.assertEqual(relative, "data/pdfs/GEM_2026_B_12345.pdf")
            self.assertEqual(saved.read_bytes(), original)

    def test_non_pdf_and_oversized_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                save_original_pdf(b"<html>not a PDF</html>", "GEM/2026/B/1", Path(tmp))
            with self.assertRaises(ValueError):
                save_original_pdf(b"%PDF" + b"x" * (25 * 1024 * 1024), "GEM/2026/B/2", Path(tmp))

    def test_expired_bid_is_not_active_but_future_bid_is(self):
        self.assertFalse(bid_is_active("2020-01-01"))
        self.assertTrue(bid_is_active("2099-12-31"))

    def test_only_official_gem_links_are_collected(self):
        html = (
            '<a href="/download/abc.pdf">Download PDF</a>'
            '<a href="https://avsar.app/file.pdf">PDF</a>'
        )
        parser = TenderLinks("https://bidplus.gem.gov.in/showbidDocument/1")
        parser.feed(html)
        self.assertEqual(parser.links, ["https://bidplus.gem.gov.in/download/abc.pdf"])


if __name__ == "__main__":
    unittest.main()
