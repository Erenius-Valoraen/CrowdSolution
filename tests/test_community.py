"""Community scam memory logic with a fake Backboard. No network."""
import unittest
from datetime import date
from unittest import mock

from legit import community, config
from legit.models import Extraction, Finding, Item, Location, Report

TODAY = date.today().isoformat()


def ext_with(*items, summary="A rental listing asking for a Zelle deposit", context="housing"):
    return Extraction(said_on=date(2026, 9, 13), context=context, summary=summary, location=Location("Austin", "TX", "US"),
                      items=list(items))


class FakeBackboard:
    """Stores memories in a list and answers the four calls community.py makes."""

    def __init__(self, memories=None, search_results=None):
        self.memories = list(memories or [])
        self.search_results = search_results or []
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and "/memories" in path:
            return {"memories": self.memories, "total_count": len(self.memories)}
        if method == "POST" and path.endswith("/memories/search"):
            return {"memories": self.search_results}
        if method == "POST" and path.endswith("/memories"):
            self.memories.append({"id": f"m{len(self.memories) + 1}", **body})
            return {"memory_id": f"m{len(self.memories)}"}
        if method == "PUT":
            mem_id = path.rsplit("/", 1)[-1]
            for m in self.memories:
                if m["id"] == mem_id:
                    m.update(body)
            return {"id": mem_id}
        raise AssertionError(f"unexpected call {method} {path}")


class CommunityTest(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch.object(config, "COMMUNITY_MEMORY", True), mock.patch.object(config, "BACKBOARD_KEY", "k"),
                   mock.patch.object(community, "_assistant_id", "asst-1")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_extract_indicators_skips_official_and_platform_domains(self):
        text = ("Email greenview.rentals@gmail.com or call (512) 555-0147. Apply at greenview-rentals.site, "
                "photos on zillow.com, verify at chase.com")
        ext = ext_with(Item(1, "entity", "Greenview", {"name": "Greenview Property Mgmt", "entity_type": "landlord"}))
        official = Finding(Item(2, "entity", "Chase", {}), "ok", "t", "s", "registry",
                           data={"claimed_domain": "chase.com", "domain_result": "brand_match"})
        found = community.extract_indicators(text, ext, [official])
        self.assertIn(("email", "greenview.rentals@gmail.com"), found)
        self.assertIn(("phone", "5125550147"), found)
        self.assertIn(("domain", "greenview-rentals.site"), found)
        self.assertIn(("name", "Greenview Property Mgmt"), found)
        domains = [v for k, v in found if k == "domain"]
        self.assertNotIn("gmail.com", domains)
        self.assertNotIn("zillow.com", domains)
        self.assertNotIn("chase.com", domains)

    def test_prices_are_not_phone_numbers(self):
        found = community.extract_indicators("Rent is $1,850,000 total or $6505550100", ext_with(), [])
        self.assertEqual([x for x in found if x[0] == "phone"], [])

    def test_format_and_parse_round_trip_from_text(self):
        ext = ext_with()
        content, meta = community.format_memory(ext, [("email", "a@b.site"), ("phone", "5125550147")],
                                                ["Hard-to-reverse payment method"], "send by zelle", 2, "2026-09-01", TODAY)
        self.assertEqual(meta["indicators"], ["email=a@b.site", "phone=5125550147"])  # flat strings: Backboard rejects nested lists
        from_meta = community.parse_memory({"id": "m1", "content": content, "metadata": meta})
        from_text = community.parse_memory({"id": "m1", "content": content, "score": 0.3})
        for record in (from_meta, from_text):
            self.assertEqual(record["kind"], "scam_report")
            self.assertEqual(record["reports"], 2)
            self.assertIn(("email", "a@b.site"), record["indicators"])
            self.assertEqual(record["red_flags"], ["Hard-to-reverse payment method"])
            self.assertEqual(record["first_seen"], "2026-09-01")
        self.assertEqual(from_text["score"], 0.3)

    def test_exact_match_flags_and_counts_again(self):
        stored_content, stored_meta = community.format_memory(
            ext_with(), [("email", "greenview.rentals@gmail.com")], ["Pay before you can verify"], "old text", 1, "2026-09-10", "2026-09-10")
        fake = FakeBackboard(memories=[{"id": "m1", "content": stored_content, "metadata": stored_meta}])
        text = "New listing! Contact greenview.rentals@gmail.com and send the deposit today."
        ext = ext_with()
        with mock.patch.object(community, "_call", fake):
            notes = []
            lookup = community.check(ext, text, [], notes)
            self.assertEqual(len(lookup.findings), 1)
            f = lookup.findings[0]
            self.assertEqual((f.status, f.checker, f.data["match"]), ("red_flag", "community", "exact"))
            self.assertEqual(f.data["matched"], [{"kind": "email", "value": "greenview.rentals@gmail.com"}])
            red = Finding(Item(1, "pattern", "deposit today", {}), "red_flag", "Pay before you can verify", "s", "patterns")
            community.remember(Report(ext, [red, f], notes), text, lookup, notes)
        self.assertEqual(len(fake.memories), 1)
        self.assertEqual(fake.memories[0]["metadata"]["reports"], 2)
        self.assertEqual(fake.memories[0]["metadata"]["last_seen"], TODAY)
        self.assertEqual(notes, [])

    def test_similar_message_is_caution_and_saved_as_new(self):
        content, _ = community.format_memory(ext_with(), [], ["Hard-to-reverse payment method"], "old", 3, "2026-09-01", "2026-09-12")
        fake = FakeBackboard(search_results=[{"id": "m9", "content": content, "score": 0.4}])
        ext = ext_with()
        text = "Room near campus, landlord overseas, e-transfer first month to hold it."
        with mock.patch.object(community, "_call", fake):
            lookup = community.check(ext, text, [], [])
            self.assertEqual([f.data["match"] for f in lookup.findings], ["similar"])
            self.assertEqual(lookup.findings[0].status, "caution")
            self.assertIsNone(lookup.same)
            red = Finding(Item(1, "pattern", "e-transfer", {}), "red_flag", "Hard-to-reverse payment method", "s", "patterns")
            community.remember(Report(ext, [red], []), text, lookup, [])
        self.assertEqual([c[0] for c in fake.calls].count("POST"), 2)  # one search, one new memory

    def test_near_identical_message_counts_as_same_report(self):
        content, _ = community.format_memory(ext_with(), [], ["x"], "old", 1, "2026-09-12", "2026-09-12")
        fake = FakeBackboard(search_results=[{"id": "m5", "content": content, "score": 0.1}])
        with mock.patch.object(community, "_call", fake):
            lookup = community.check(ext_with(), "same text", [], [])
        self.assertEqual(lookup.findings[0].data["match"], "same_message")
        self.assertEqual(lookup.findings[0].status, "red_flag")
        self.assertEqual(lookup.same["id"], "m5")

    def test_far_match_and_clean_reports_are_ignored(self):
        content, _ = community.format_memory(ext_with(), [], ["x"], "old", 1, TODAY, TODAY)
        fake = FakeBackboard(search_results=[{"id": "m1", "content": content, "score": 0.8}])
        ext = ext_with(summary="An honest apartment listing with in-person tours")
        with mock.patch.object(community, "_call", fake):
            lookup = community.check(ext, "2BR, $1,850/month, tours Saturday", [], [])
            self.assertEqual(lookup.findings, [])
            ok = Finding(Item(1, "price", "$1,850", {}), "ok", "Rent", "s", "benchmark")
            community.remember(Report(ext, [ok], []), "2BR, $1,850/month", lookup, [])
        self.assertFalse(any(c[0] == "POST" and c[1].endswith("/memories") for c in fake.calls))

    def test_errors_become_notes(self):
        def broken(*a, **k):
            raise community.CommunityError("Backboard unreachable: timeout")

        notes = []
        with mock.patch.object(community, "_call", broken):
            lookup = community.check(ext_with(), "contact a@b.site", [], notes)
        self.assertFalse(lookup.checked)
        self.assertTrue(notes and "unavailable" in notes[0])

    def test_disabled(self):
        with mock.patch.object(config, "COMMUNITY_MEMORY", False):
            self.assertFalse(community.enabled())
            self.assertFalse(community.check(ext_with(), "a@b.site", [], []).checked)


if __name__ == "__main__":
    unittest.main()
