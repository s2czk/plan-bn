import unittest

from audit_plan import check_overlaps, compare_days


class ScheduleAuditTests(unittest.TestCase):
    def test_equal_published_and_reparsed_days_have_no_differences(self):
        days = {
            "2026-11-15": {
                "mode": "ZDALNE",
                "items": [{"time": "08:00-09:30", "title": "Ekonomia"}],
            }
        }
        self.assertEqual(compare_days(days, days), {"missing": [], "added": [], "changed": []})

    def test_schedule_comparison_reports_missing_added_and_changed_days(self):
        stored = {
            "2026-11-14": {"items": [{"time": "08:00-09:30", "title": "A"}]},
            "2026-11-15": {"items": [{"time": "08:00-09:30", "title": "B"}]},
        }
        parsed = {
            "2026-11-15": {"items": [{"time": "09:00-10:30", "title": "B"}]},
            "2026-11-16": {"items": [{"time": "08:00-09:30", "title": "C"}]},
        }
        self.assertEqual(
            compare_days(stored, parsed),
            {"missing": ["2026-11-14"], "added": ["2026-11-16"], "changed": ["2026-11-15"]},
        )

    def test_adjacent_classes_are_not_reported_as_overlapping(self):
        days = {
            "2026-11-15": {
                "items": [
                    {"time": "08:00-09:30", "title": "A"},
                    {"time": "09:30-11:00", "title": "B"},
                ]
            }
        }
        self.assertEqual(check_overlaps(days), [])

    def test_nested_overlaps_are_all_detected(self):
        days = {
            "2026-11-15": {
                "items": [
                    {"time": "08:00-12:00", "title": "A"},
                    {"time": "09:00-10:00", "title": "B"},
                    {"time": "11:00-13:00", "title": "C"},
                ]
            }
        }
        overlaps = check_overlaps(days)
        self.assertEqual(len(overlaps), 2)
        self.assertEqual(
            {(item["first"], item["second"]) for item in overlaps},
            {("A", "B"), ("A", "C")},
        )


if __name__ == "__main__":
    unittest.main()
