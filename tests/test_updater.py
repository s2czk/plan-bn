import unittest

from updater import build_change_notifications, merge_adjacent_blocks


def block(start, end, title="Ekonomia", lecturer="dr A. Kowalski", class_type="Wykł.", remote=True, room=""):
    return {
        "start": start,
        "end": end,
        "title": title,
        "lecturer": lecturer,
        "type": class_type,
        "remote": remote,
        "room": room,
    }


class MergeAdjacentBlocksTests(unittest.TestCase):
    def test_merges_only_contiguous_identical_blocks(self):
        result = merge_adjacent_blocks([
            block("15:45", "16:30"),
            block("15:00", "15:45"),
        ])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["start"], "15:00")
        self.assertEqual(result[0]["end"], "16:30")

    def test_does_not_merge_if_there_is_a_gap(self):
        result = merge_adjacent_blocks([block("15:00", "15:45"), block("16:00", "16:30")])
        self.assertEqual(len(result), 2)

    def test_does_not_merge_different_type_or_mode(self):
        result = merge_adjacent_blocks([
            block("15:00", "15:45"),
            block("15:45", "16:30", class_type="Ćw."),
            block("16:30", "17:15", remote=False),
        ])
        self.assertEqual(len(result), 3)


class NotificationDiffTests(unittest.TestCase):
    def test_unchanged_plan_has_no_notifications(self):
        day = {"mode": "ZDALNE", "items": [{"time": "15:00-16:30", "title": "Ekonomia", "lecturer": "dr A. Kowalski", "type": "Wykł."}]}
        self.assertEqual(build_change_notifications({"2026-11-12": day}, {"2026-11-12": day}, "abc"), [])

    def test_time_change_is_reported(self):
        old = {"mode": "ZDALNE", "items": [{"time": "15:00-16:30", "title": "Ekonomia", "lecturer": "dr A. Kowalski", "type": "Wykł."}]}
        new = {"mode": "ZDALNE", "items": [{"time": "16:00-17:30", "title": "Ekonomia", "lecturer": "dr A. Kowalski", "type": "Wykł."}]}
        changes = build_change_notifications({"2026-11-12": old}, {"2026-11-12": new}, "abc")
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["type"], "changed")
        self.assertTrue(any("Godzina:" in detail for detail in changes[0]["details"]))

    def test_added_and_cancelled_classes_are_reported(self):
        old = {"mode": "ZDALNE", "items": [{"time": "15:00-16:30", "title": "Ekonomia", "lecturer": "dr A. Kowalski", "type": "Wykł."}]}
        new = {"mode": "ZDALNE", "items": [{"time": "18:00-19:30", "title": "Socjologia", "lecturer": "dr B. Nowak", "type": "Wykł."}]}
        changes = build_change_notifications({"2026-11-12": old}, {"2026-11-12": new}, "abc")
        self.assertEqual({change["type"] for change in changes}, {"added", "cancelled"})


if __name__ == "__main__":
    unittest.main()
