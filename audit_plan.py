# AUDYT PDF: weryfikacja czterech czerwonych wpisów z powodu zwolnienia lekarskiego na 19.11.2026.
import hashlib
import io
import json
import re
from pathlib import Path

import pdfplumber
import requests

from updater import (
    HEADERS,
    find_bn_resource_link,
    parse_single_page,
    parse_week_page,
    validate_schedule,
)


def minutes(value):
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value))
    if not match:
        raise ValueError(f"Nieprawidłowy czas: {value}")
    return int(match.group(1)) * 60 + int(match.group(2))


def check_overlaps(days):
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
                overlaps.append({
                    "date": date,
                    "first": first[2].get("title"),
                    "first_time": first[2].get("time"),
                    "second": second[2].get("title"),
                    "second_time": second[2].get("time"),
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


def check_known_medical_leave_example(days):
    """Kontrola referencyjna z oryginalnego zrzutu PDF: cztery czerwone pola 19.11."""
    expected_times = ["15:00-15:45", "15:45-16:30", "16:45-17:30", "17:30-18:15"]
    items = (days.get("2026-11-19") or {}).get("items", [])
    actual = [
        item for item in items
        if item.get("title") == "Podstawy ekonomii"
        and item.get("status") == "ODWOŁANE"
        and item.get("status_reason") == "Zwolnienie lekarskie"
    ]
    actual_times = sorted(item.get("time", "") for item in actual)
    return {
        "result": "PASS" if actual_times == expected_times else "FAIL",
        "expected_times": expected_times,
        "actual_times": actual_times,
        "count": len(actual),
    }


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
            "PDF zmienił się od ostatniej publikacji. "
            "Przerwano audyt porównawczy, aby nie porównywać różnych wersji planu."
        )

    parsed_days = {}
    duplicate_dates = []
    seen_dates = set()
    weekly_page_count = 0
    pages_with_date_but_no_classes = []
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
                        pages_with_date_but_no_classes.append({"date": date, "page": page_number})
                continue

            page_text = page.extract_text() or ""
            date, day = parse_single_page(page_text)
            if not date:
                continue
            if date in seen_dates:
                duplicate_dates.append({"date": date, "page": page_number})
                continue
            seen_dates.add(date)
            if day:
                parsed_days[date] = day
            else:
                pages_with_date_but_no_classes.append({"date": date, "page": page_number})

    validate_schedule(parsed_days)
    if duplicate_dates:
        raise RuntimeError(f"PDF zawiera powtórzone strony/daty: {duplicate_dates[:10]}")

    stored_payload = json.loads(Path("schedule.json").read_text(encoding="utf-8"))
    stored_days = stored_payload.get("days") or {}
    comparison = compare_days(stored_days, parsed_days)
    overlaps = check_overlaps(parsed_days)
    medical_leave_check = check_known_medical_leave_example(parsed_days)

    total_items = sum(len(day.get("items", [])) for day in parsed_days.values())
    cancelled_items = sum(
        1 for day in parsed_days.values() for item in day.get("items", [])
        if item.get("status") == "ODWOŁANE"
    )
    print(json.dumps({
        "audit": "FULL_PDF_PARSE",
        "result": "PASS" if not any(comparison.values()) and not overlaps else "FAIL",
        "source_url": resource_url,
        "source_label": label,
        "pdf_bytes": len(pdf_bytes),
        "pdf_sha256": source_hash,
        "pdf_pages": page_count,
        "weekly_pages": weekly_page_count,
        "dated_pages_without_classes": pages_with_date_but_no_classes,
        "parsed_days": len(parsed_days),
        "parsed_classes": total_items,
        "cancelled_items": cancelled_items,
        "reference_medical_leave_check": medical_leave_check,
        "published_days": len(stored_days),
        "published_classes": sum(len(day.get("items", [])) for day in stored_days.values()),
        "comparison": comparison,
        "overlaps": overlaps[:20],
        "overlap_count": len(overlaps),
    }, ensure_ascii=False, indent=2))

    if weekly_page_count and weekly_page_count == page_count and len(parsed_days) != page_count * 7:
        raise SystemExit("Pełny audyt PDF nie znalazł dokładnie 7 dat na każdej stronie tygodniowej.")

    if medical_leave_check["result"] != "PASS":
        raise SystemExit("Pełny audyt PDF nie rozpoznał czterech odwołanych pól z powodu zwolnienia lekarskiego z oryginalnego zrzutu.")
    if any(comparison.values()) or overlaps:
        raise SystemExit("Pełny audyt PDF nie przeszedł: wynik parsowania różni się od opublikowanych danych lub zawiera kolizje godzin.")


if __name__ == "__main__":
    main()
