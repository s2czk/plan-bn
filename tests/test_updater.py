import unittest

from updater import build_change_notifications, clean_subject_title, extract_group_labels, group_change_notifications, merge_adjacent_blocks, parse_single_page


def block(start, end, title="Ekonomia", lecturer="dr A. Kowalski", class_type="wykład", remote=True, room=""):
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
    def test_merges_same_subject_across_any_gap_and_metadata(self):
        result = merge_adjacent_blocks([
            block("08:00", "08:45", title="Administracja publiczna"),
            block("09:00", "09:45", title="Administracja publiczna – wykład", lecturer="dr Anna Nowak", class_type="ćwiczenia"),
            block("11:00", "11:45", title="Administracja publiczna grupa 1", lecturer="mgr Jan Kowalski", class_type="wykład"),
        ])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["start"], "08:00")
        self.assertEqual(result[0]["end"], "11:45")
        self.assertEqual(result[0]["lecturer"], "dr A. Kowalski / dr Anna Nowak / mgr Jan Kowalski")
        self.assertEqual(result[0]["type"], "wykład / ćwiczenia")
        self.assertEqual(result[0]["group"], "grupa 1")
    
    def test_different_subject_breaks_merging(self):
        result = merge_adjacent_blocks([
            block("08:00", "08:45", title="Administracja publiczna"),
            block("09:00", "09:45", title="Historia Polski"),
            block("11:00", "11:45", title="Administracja publiczna"),
        ])
        self.assertEqual(len(result), 3)

    def test_only_group_codes_are_preserved(self):
        self.assertEqual(extract_group_labels("Administracja publiczna grupa 1"), ["grupa 1"])
        self.assertEqual(extract_group_labels("Bezpieczeństwo i higiena pracy grupa ogólna"), [])

    def test_subject_suffix_time_is_removed(self):
        self.assertEqual(clean_subject_title("Podstawy filozofii 10:00"), "Podstawy filozofii")
        self.assertEqual(clean_subject_title("Administracja publiczna – wykład"), "Administracja publiczna")

    def test_pdf_room_type_and_academic_year_are_removed_from_title(self):
        self.assertEqual(
            clean_subject_title("Kwalifikowana pierwsza pomoc medyczna 11 Ćwiczenia I (2026/2027)"),
            "Kwalifikowana pierwsza pomoc medyczna",
        )

    def test_room_does_not_get_time_suffix(self):
        sample = (
            "lis 7, 2026 "
            "08:00-08:45 Administracja publiczna 9:00 mgr Jan Kowalski Wykład Zdalnie "
            "08:45-09:30 Administracja publiczna – ćwiczenia 10:00 mgr Anna Nowak Ćwiczenia Zdalnie"
        )
        date, day = parse_single_page(sample)
        self.assertEqual(date, "2026-11-07")
        self.assertEqual(len(day["items"]), 1)
        self.assertEqual(day["items"][0]["title"], "Administracja publiczna")
        self.assertEqual(day["items"][0]["time"], "08:00-09:30")
        self.assertEqual(day["items"][0]["lecturer"], "mgr Jan Kowalski / mgr Anna Nowak")
        self.assertEqual(day["items"][0]["type"], "wykład / ćwiczenia")
        self.assertEqual(day["mode"], "ZDALNE")


class NotificationDiffTests(unittest.TestCase):
    def test_unchanged_plan_has_no_notifications(self):
        day = {"mode": "ZDALNE", "items": [{"time": "15:00-16:30", "title": "Ekonomia", "lecturer": "dr A. Kowalski", "type": "wykład"}]}
        self.assertEqual(build_change_notifications({"2026-11-12": day}, {"2026-11-12": day}, "abc"), [])

    def test_time_change_is_reported(self):
        old = {"mode": "ZDALNE", "items": [{"time": "15:00-16:30", "title": "Ekonomia", "lecturer": "dr A. Kowalski", "type": "wykład"}]}
        new = {"mode": "ZDALNE", "items": [{"time": "16:00-17:30", "title": "Ekonomia", "lecturer": "dr A. Kowalski", "type": "wykład"}]}
        changes = build_change_notifications({"2026-11-12": old}, {"2026-11-12": new}, "abc")
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["type"], "changed")
        self.assertTrue(any("Godzina:" in detail for detail in changes[0]["details"]))

    def test_added_and_cancelled_classes_are_reported(self):
        old = {"mode": "ZDALNE", "items": [{"time": "15:00-16:30", "title": "Ekonomia", "lecturer": "dr A. Kowalski", "type": "wykład"}]}
        new = {"mode": "ZDALNE", "items": [{"time": "18:00-19:30", "title": "Socjologia", "lecturer": "dr B. Nowak", "type": "wykład"}]}
        changes = build_change_notifications({"2026-11-12": old}, {"2026-11-12": new}, "abc")
        self.assertEqual({change["type"] for change in changes}, {"added", "cancelled"})

    def test_grouped_push_message_contains_action_and_change_details(self):
        raw = [{
            "id": "a",
            "date": "2026-11-12",
            "type": "changed",
            "message": "Ekonomia · 08:00-09:30",
            "details": ["Godzina: 08:00-09:30 → 10:00-11:30", "Sala: 105 → 106"],
        }]
        grouped = group_change_notifications(raw, "hash", "2026-11-07 12:00")
        self.assertIn("ZMIENIONO", grouped[0]["push_message"])
        self.assertIn("Godzina:", grouped[0]["push_message"])
        self.assertIn("Sala:", grouped[0]["push_message"])

    def test_group_change_is_reported(self):
        old = {"mode": "ZDALNE", "items": [{"time": "08:00-09:30", "title": "Administracja publiczna", "lecturer": "dr A. Kowalski", "type": "ćwiczenia", "group": "grupa 1"}]}
        new = {"mode": "ZDALNE", "items": [{"time": "08:00-09:30", "title": "Administracja publiczna", "lecturer": "dr A. Kowalski", "type": "ćwiczenia", "group": "grupa 2"}]}
        changes = build_change_notifications({"2026-11-12": old}, {"2026-11-12": new}, "abc")
        self.assertEqual(len(changes), 1)
        self.assertTrue(any("Grupa:" in detail for detail in changes[0]["details"]))

    def test_several_changes_are_grouped_for_same_day(self):
        raw = [
            {"id": "a", "date": "2026-11-12", "type": "added", "message": "Historia"},
            {"id": "b", "date": "2026-11-12", "type": "changed", "message": "Ekonomia"},
            {"id": "c", "date": "2026-11-13", "type": "cancelled", "message": "Prawo"},
        ]
        grouped = group_change_notifications(raw, "hash", "2026-11-07 12:00")
        self.assertEqual(len(grouped), 2)
        self.assertEqual(len(grouped[0]["events"]), 2)
        self.assertEqual(grouped[0]["url"], "./?date=2026-11-12")


if __name__ == "__main__":
    unittest.main()
