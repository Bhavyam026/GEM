import unittest

from scripts.scan_gem import (
    normalize_bid_number, record_key, dedupe_records,
    buyer_matches, category_for, location_matches,
)
from scripts.pdf_extract import TenderLinks


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

    def test_categories_are_classified_from_bid_text(self):
        self.assertEqual(category_for("Supply of IP CCTV cameras"), "CCTV & Surveillance")
        self.assertEqual(category_for("Supply of LAN Switches"), "Networking")
        self.assertEqual(category_for("Fire alarm and smoke detector"), "Fire Safety")
        self.assertEqual(category_for("unrelated stationery"), "")

    def test_location_matching_includes_bo isar_and_pin_codes(self):
        self.assertEqual(location_matches("Delivery at Tarapur Site, Boisar, Palghar 401504"),
                         ["Palghar", "Boisar"])
        self.assertEqual(location_matches("Mumbai 400094"), ["Mumbai"])
        self.assertEqual(location_matches("Thane 400601"), [])
        self.assertEqual(location_matches("Chennai 600001"), [])


class PdfLinkTests(unittest.TestCase):
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
