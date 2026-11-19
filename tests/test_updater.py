import unittest

from updater import build_change_notifications, clean_subject_title, extract_group_labels, extract_red_status_boxes, group_change_notifications, merge_adjacent_blocks, merge_pending_notifications, parse_single_page, parse_week_page_words


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


class RedStatusBoxExtractionTests(unittest.TestCase):
    def test_red_rectangle_objects_are_detected_even_when_not_curves(self):
        red_rect = {
            "stroking_color": (1.0, 0.0, 0.0), "stroke": True,
            "x0": 150.0, "x1": 261.0, "top": 95.0, "bottom": 137.0,
        }
        page = type("Page", (), {"rects": [red_rect], "curves": []})()
        self.assertEqual(
            extract_red_status_boxes(page),
            [{"x0": 150.0, "x1": 261.0, "top": 95.0, "bottom": 137.0}],
        )

    def test_non_red_rectangles_and_small_red_shapes_are_ignored(self):
        page = type("Page", (), {"rects": [
            {"stroking_color": (0.5, 0.5, 0.5), "stroke": True,
             "x0": 150.0, "x1": 261.0, "top": 95.0, "bottom": 137.0},
            {"stroking_color": (1.0, 0.0, 0.0), "stroke": True,
             "x0": 150.0, "x1": 160.0, "top": 95.0, "bottom": 137.0},
        ], "curves": []})()
        self.assertEqual(extract_red_status_boxes(page), [])


class MergeAdjacentBlocksTests(unittest.TestCase):
    def test_merges_only_contiguous_same_subject_with_identical_metadata(self):
        result = merge_adjacent_blocks([
            block("08:00", "08:45", title="Administracja publiczna"),
            block("08:45", "09:30", title="Administracja publiczna"),
            block("10:00", "10:45", title="Administracja publiczna", lecturer="dr Anna Nowak", class_type="ćwiczenia"),
        ])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["start"], "08:00")
        self.assertEqual(result[0]["end"], "09:30")
        self.assertEqual(result[1]["start"], "10:00")
        self.assertEqual(result[1]["lecturer"], "dr Anna Nowak")

    def test_same_subject_across_gap_is_not_merged(self):
        result = merge_adjacent_blocks([
            block("08:00", "08:45", title="Administracja publiczna"),
            block("09:00", "09:45", title="Administracja publiczna"),
        ])
        self.assertEqual(len(result), 2)
    
    def test_different_subject_breaks_merging(self):
        result = merge_adjacent_blocks([
            block("08:00", "08:45", title="Administracja publiczna"),
            block("09:00", "09:45", title="Historia Polski"),
            block("11:00", "11:45", title="Administracja publiczna"),
        ])
        self.assertEqual(len(result), 3)

    def test_weekly_pdf_columns_are_split_into_separate_dates_and_subjects(self):
        headers = [
            ("pon.", 87.2), ("wt.", 201.1), ("śr.", 313.9), ("czw.", 422.1),
            ("pt.", 536.3), ("sob.", 645.2), ("niedz.", 753.5),
        ]
        words = [{"text": label, "x0": x, "x1": x + 20, "top": 55.4} for label, x in headers]
        # Poniedziałek jest pusty. Pierwsze zajęcia zaczynają się w kolumnie wtorku.
        words += [
            {"text": "16:45–17:30", "x0": 161.1, "top": 100.0},
            {"text": "Wszyscy", "x0": 241.0, "top": 100.0},
            {"text": "Elementy", "x0": 161.1, "top": 105.0},
            {"text": "samoobrony", "x0": 188.0, "top": 105.0},
            {"text": "mgr", "x0": 161.1, "top": 110.0},
            {"text": "Sebastian", "x0": 172.3, "top": 110.0},
            {"text": "Tałaj", "x0": 197.5, "top": 110.0},
            {"text": "H24", "x0": 251.9, "top": 110.0},
            {"text": "Ćwiczenia", "x0": 161.1, "top": 115.0},
            {"text": "16:45–17:30", "x0": 272.6, "top": 100.0},
            {"text": "Wszyscy", "x0": 352.6, "top": 100.0},
            {"text": "Komunikacja", "x0": 272.6, "top": 105.0},
            {"text": "interpersonalna", "x0": 308.8, "top": 105.0},
            {"text": "mgr", "x0": 272.6, "top": 110.0},
            {"text": "Sylwia", "x0": 283.8, "top": 110.0},
            {"text": "Hille-Jarząbek", "x0": 300.7, "top": 110.0},
            {"text": "104", "x0": 364.0, "top": 110.0},
            {"text": "Ćwiczenia", "x0": 272.6, "top": 115.0},
        ]
        parsed = parse_week_page_words("2026-11-16", words, 841.9, red_boxes=[{"x0": 150, "x1": 261, "top": 95, "bottom": 120}])
        self.assertEqual(len(parsed), 7)
        self.assertEqual(parsed["2026-11-16"]["items"], [])
        self.assertEqual(parsed["2026-11-17"]["items"][0]["title"], "Elementy samoobrony")
        self.assertEqual(parsed["2026-11-18"]["items"][0]["title"], "Komunikacja interpersonalna")
        self.assertEqual(parsed["2026-11-17"]["items"][0]["room"], "H24")
        self.assertEqual(parsed["2026-11-17"]["items"][0]["status"], "ODWOŁANE")
        self.assertEqual(parsed["2026-11-17"]["items"][0]["status_source"], "PDF_RED_FRAME")
        self.assertEqual(parsed["2026-11-18"]["items"][0]["room"], "104")
        self.assertNotEqual(
            parsed["2026-11-17"]["items"][0]["title"],
            parsed["2026-11-18"]["items"][0]["title"],
        )

    def test_medical_leave_marker_marks_class_cancelled_and_keeps_original_teacher(self):
        sample = (
            "lis 19, 2026 "
            "15:00-15:45 Podstawy ekonomii Wszyscy dr Małgorzata Guziń…Zwolnienie lekar… Ćwiczenia I (2026/2027)"
        )
        date, day = parse_single_page(sample, [True])
        self.assertEqual(date, "2026-11-19")
        self.assertEqual(len(day["items"]), 1)
        item = day["items"][0]
        self.assertEqual(item["title"], "Podstawy ekonomii")
        self.assertEqual(item["lecturer"], "dr Małgorzata Guziń")
        self.assertEqual(item["status"], "ODWOŁANE")
        self.assertEqual(item["status_reason"], "Zwolnienie lekarskie")
        self.assertEqual(item["status_source"], "PDF_TEXT_AND_RED_FRAME")

    def test_red_frame_without_text_still_marks_item_cancelled(self):
        sample = "lis 19, 2026 15:00-15:45 Podstawy ekonomii dr Małgorzata Guziń Ćwiczenia"
        _, day = parse_single_page(sample, [True])
        item = day["items"][0]
        self.assertEqual(item["status"], "ODWOŁANE")
        self.assertEqual(item["status_reason"], "Czerwona ramka w źródłowym PDF")
        self.assertEqual(item["status_source"], "PDF_RED_FRAME")

    def test_four_medical_leave_slots_remain_four_separate_cancelled_items(self):
        slots = ["15:00-15:45", "15:45-16:30", "16:45-17:30", "17:30-18:15"]
        sample = "lis 19, 2026 " + " ".join(
            slot + " Podstawy ekonomii Wszyscy dr Małgorzata Guziń…Zwolnienie lekar… Ćwiczenia"
            for slot in slots
        )
        _, day = parse_single_page(sample, [True, True, True, True])
        self.assertEqual([item["time"] for item in day["items"]], slots)
        self.assertTrue(all(item["status"] == "ODWOŁANE" for item in day["items"]))
        self.assertTrue(all(item["status_reason"] == "Zwolnienie lekarskie" for item in day["items"]))

    def test_status_transition_to_medical_leave_is_a_cancellation_notification(self):
        old_day = {"mode": "STACJONARNE", "items": [{
            "time": "15:00-16:30", "title": "Podstawy ekonomii",
            "lecturer": "dr Małgorzata Guziń", "type": "ćwiczenia", "mode": "STACJONARNE"
        }]}
        new_day = {"mode": "STACJONARNE", "items": [{
            "time": "15:00-16:30", "title": "Podstawy ekonomii",
            "lecturer": "dr Małgorzata Guziń", "type": "ćwiczenia", "mode": "STACJONARNE",
            "status": "ODWOŁANE", "status_reason": "Zwolnienie lekarskie"
        }]}
        changes = build_change_notifications({"2026-11-19": old_day}, {"2026-11-19": new_day}, "medical-leave")
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["type"], "cancelled")
        self.assertIn("Zwolnienie lekarskie", " ".join(changes[0]["details"]))

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
        self.assertEqual(len(day["items"]), 2)
        self.assertEqual(day["items"][0]["title"], "Administracja publiczna")
        self.assertEqual(day["items"][0]["time"], "08:00-08:45")
        self.assertEqual(day["items"][0]["lecturer"], "mgr Jan Kowalski")
        self.assertEqual(day["items"][0].get("room", ""), "")
        self.assertEqual(day["items"][1]["title"], "Administracja publiczna")
        self.assertEqual(day["items"][1]["time"], "08:45-09:30")
        self.assertEqual(day["items"][1]["lecturer"], "mgr Anna Nowak")
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



class PendingPushQueueTests(unittest.TestCase):
    def test_pending_notifications_are_preserved_and_new_ones_are_appended(self):
        old = [{"id": "old-1", "message": "Niewysłane"}]
        new = [{"id": "new-1", "message": "Nowe"}]
        self.assertEqual(
            merge_pending_notifications(old, new),
            old + new,
        )

    def test_duplicate_notification_ids_are_not_queued_twice(self):
        old = [{"id": "same-id", "message": "Pierwsza wersja"}]
        new = [{"id": "same-id", "message": "Duplikat"}, {"id": "new-id", "message": "Nowe"}]
        self.assertEqual(
            merge_pending_notifications(old, new),
            [old[0], new[1]],
        )

    def test_invalid_notification_without_id_is_rejected(self):
        with self.assertRaises(ValueError):
            merge_pending_notifications([], [{"message": "Bez identyfikatora"}])

    def test_pending_queue_is_not_mutated(self):
        old = [{"id": "old-1"}]
        new = [{"id": "new-1"}]
        merge_pending_notifications(old, new)
        self.assertEqual(old, [{"id": "old-1"}])
        self.assertEqual(new, [{"id": "new-1"}])


if __name__ == "__main__":
    unittest.main()
