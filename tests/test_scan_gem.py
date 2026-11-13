import unittest

from scripts.scan_gem import normalize_bid_number, record_key, dedupe_records


class DeduplicationTests(unittest.TestCase):
    def test_bid_number_normalizes_case_and_whitespace(self):
        self.assertEqual(
            normalize_bid_number(" gem / 2026 / b / 12345 "),
            "GEM/2026/B/12345",
        )

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


if __name__ == "__main__":
    unittest.main()
