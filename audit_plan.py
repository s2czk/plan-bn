# Obowiązkowy audyt źródłowego PDF przed publikacją harmonogramu.
import hashlib
import io
import json
import re
from pathlib import Path

import pdfplumber
import requests

from updater import (
    HEADERS,
    extract_red_frame_flags,
    extract_red_status_boxes,
    extract_weekday_labels,
    find_bn_resource_link,
    parse_single_page,
    parse_week_page,
    validate_day_source_text,
    validate_pdf_page_coverage,
    validate_schedule,
)


def minutes(value):
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value))
    if not match:
        raise ValueError(f"Nieprawidłowy czas: {value}")
    return int(match.group(1)) * 60 + int(match.group(2))


def _group_set(item):
    return {
        group.strip().casefold()
        for group in re.split(r"\s*/\s*", str(item.get("group") or ""))
        if group.strip()
    }


def check_overlaps(days):
    """Wykrywa kolizje dla tej samej grupy; równoległe grupy nie są konfliktem."""
    overlaps = []
    for date, day in days.items():
        events = []
        for item in day.get("items", []):
            start, end = item["time"].split("-", 1)
            events.append((minutes(start), minutes(end), item))
        events.sort(key=lambda event: (event[0], event[1]))
        for index, first in enumerate(events):
            for second in events[index + 1:]:
                if second[0] >= first[1]:
                    break
                first_groups = _group_set(first[2])
                second_groups = _group_set(second[2])
                if first_groups and second_groups and first_groups.isdisjoint(second_groups):
                    continue
                overlaps.append({
                    "date": date,
                    "first": first[2].get("title"),
                    "first_time": first[2].get("time"),
                    "first_group": first[2].get("group", ""),
                    "second": second[2].get("title"),
                    "second_time": second[2].get("time"),
                    "second_group": second[2].get("group", ""),
                })
    return overlaps


def compare_days(stored_days, parsed_days):
    stored_dates = set(stored_days)
    parsed_dates = set(parsed_days)
    missing = sorted(stored_dates - parsed_dates)
    added = sorted(parsed_dates - stored_dates)
    changed = sorted(
        date for date in stored_dates & parsed_dates
        if stored_days[date] != parsed_days[date]
    )
    return {"missing": missing, "added": added, "changed": changed}


def main():
    resource_url, label = find_bn_resource_link()
    print(f"Źródło PDF: {resource_url}")
    print(f"Etykieta źródła: {label}")

    label_normalized = label.casefold()
    if "bn" not in label_normalized or "mgr" in label_normalized or "niestacjonarne" in label_normalized:
        raise RuntimeError(f"Wybrano nieoczekiwany zasób zamiast BN I stacjonarnego: {label}")

    response = requests.get(resource_url, headers=HEADERS, timeout=45, allow_redirects=True)
    response.raise_for_status()
    pdf_bytes = response.content
    if b"%PDF-" not in pdf_bytes[:1024]:
        raise RuntimeError("Źródło nie zwróciło prawidłowego pliku PDF.")

    source_hash = hashlib.sha256(pdf_bytes).hexdigest()
    expected_hash = Path("last_hash.txt").read_text(encoding="utf-8").strip()
    if source_hash != expected_hash:
        raise RuntimeError(
            "PDF zmienił się między parsowaniem a audytem. "
            "Przerwano publikację; poprzedni plan pozostaje bez zmian."
        )

    parsed_days = {}
    seen_dates = set()
    duplicate_dates = []
    weekly_page_count = 0
    parsed_page_count = 0
    pages_without_classes = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page_count = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            weekly_days = parse_week_page(page)
            if weekly_days is not None:
                weekly_page_count += 1
                for date, day in weekly_days.items():
                    if date in seen_dates:
                        duplicate_dates.append({"date": date, "page": page_number})
                        continue
                    seen_dates.add(date)
                    parsed_days[date] = day
                    if not day.get("items"):
                        pages_without_classes.append({"date": date, "page": page_number})
                parsed_page_count += 1
                continue

            page_words = page.extract_words(
                x_tolerance=2,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=False,
            )
            weekday_labels = extract_weekday_labels(page_words)
            if weekday_labels:
                raise RuntimeError(
                    f"Audyt: strona {page_number} zawiera nagłówki dni {sorted(weekday_labels)}, "
                    "ale nie dała się bezpiecznie podzielić na siedem kolumn."
                )

            page_text = page.extract_text() or ""
            red_frame_flags = extract_red_frame_flags(page_words, extract_red_status_boxes(page))
            date, day = parse_single_page(page_text, red_frame_flags)
            if not date:
                raise RuntimeError(f"Audyt: strona {page_number} nie została przypisana do żadnej daty.")
            if date in seen_dates:
                duplicate_dates.append({"date": date, "page": page_number})
                continue
            day = day or {"mode": "STACJONARNE", "items": []}
            validate_day_source_text(date, page_text, day, red_frame_flags)
            seen_dates.add(date)
            parsed_days[date] = day
            if not day.get("items"):
                pages_without_classes.append({"date": date, "page": page_number})
            parsed_page_count += 1

    validate_pdf_page_coverage(page_count, parsed_page_count, weekly_page_count, len(parsed_days))
    validate_schedule(parsed_days)
    if duplicate_dates:
        raise RuntimeError(f"PDF zawiera powtórzone strony/daty: {duplicate_dates[:10]}")

    stored_payload = json.loads(Path("schedule.json").read_text(encoding="utf-8"))
    stored_days = stored_payload.get("days") or {}
    comparison = compare_days(stored_days, parsed_days)
    overlaps = check_overlaps(parsed_days)
    cancelled_by_reason = {}
    for day in parsed_days.values():
        for item in day.get("items", []):
            if item.get("status") == "ODWOŁANE":
                reason = item.get("status_reason") or "Bez podanej przyczyny"
                cancelled_by_reason[reason] = cancelled_by_reason.get(reason, 0) + 1

    total_items = sum(len(day.get("items", [])) for day in parsed_days.values())
    audit_passed = not any(comparison.values()) and not overlaps
    report = {
        "audit": "FULL_PDF_PARSE",
        "result": "PASS" if audit_passed else "FAIL",
        "source_url": resource_url,
        "source_label": label,
        "pdf_bytes": len(pdf_bytes),
        "pdf_sha256": source_hash,
        "pdf_pages": page_count,
        "classified_pages": parsed_page_count,
        "weekly_pages": weekly_page_count,
        "parsed_days": len(parsed_days),
        "parsed_classes": total_items,
        "cancelled_items": sum(cancelled_by_reason.values()),
        "cancelled_by_reason": cancelled_by_reason,
        "pages_without_classes": pages_without_classes,
        "published_days": len(stored_days),
        "published_classes": sum(len(day.get("items", [])) for day in stored_days.values()),
        "comparison": comparison,
        "overlaps": overlaps[:20],
        "overlap_count": len(overlaps),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not audit_passed:
        raise SystemExit(
            "Pełny audyt PDF nie przeszedł: wynik parsowania różni się od opublikowanych danych "
            "lub wykryto kolizje zajęć dla tej samej grupy."
        )


if __name__ == "__main__":
    main()
