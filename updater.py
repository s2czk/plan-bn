import hashlib
import io
import json
import os
import re
from datetime import datetime
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup

COURSE_URL = "https://www.edukacja.pans-koszalin.pl/course/view.php?id=9443"
FALLBACK_RESOURCE_URL = "https://www.edukacja.pans-koszalin.pl/mod/resource/view.php?id=134991"
HASH_FILE = "last_hash.txt"
OUTPUT_JSON = "schedule.json"
NOTIFICATIONS_JSON = "notifications.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
MONTHS_MAP = {
    "sty": "01", "lut": "02", "mar": "03", "kwi": "04", "maj": "05", "cze": "06",
    "lip": "07", "sie": "08", "wrz": "09", "paź": "10", "paz": "10", "lis": "11", "gru": "12",
}


def find_bn_resource_link():
    """Znajduje aktualny zasób planu BN I stopnia, studia stacjonarne."""
    try:
        response = requests.get(COURSE_URL, headers=HEADERS, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            label = " ".join(anchor.get_text().split()).lower()
            href = anchor["href"]
            if "mod/resource/view.php" in href and "bn" in label:
                if "mgr" not in label and "niestacjonarne" not in label:
                    return urljoin(COURSE_URL, href), label
    except Exception as exc:
        print(f"Ostrzeżenie podczas skanowania kursu: {exc}")
    return FALLBACK_RESOURCE_URL, "plan BN I stacjonarne (link bezpośredni)"


def time_to_minutes(value):
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value))
    if not match:
        raise ValueError(f"Nieprawidłowy czas: {value}")
    return int(match.group(1)) * 60 + int(match.group(2))


def merge_adjacent_blocks(raw_blocks):
    """Scalaj tylko ciągłe bloki o identycznym przedmiocie, prowadzącym i trybie."""
    ordered = sorted(raw_blocks, key=lambda item: time_to_minutes(item["start"]))
    grouped = []
    for block in ordered:
        if grouped:
            previous = grouped[-1]
            same_session = (
                time_to_minutes(previous["end"]) == time_to_minutes(block["start"])
                and previous["title"].strip().casefold() == block["title"].strip().casefold()
                and previous["lecturer"].strip().casefold() == block["lecturer"].strip().casefold()
                and previous["type"].strip().casefold() == block["type"].strip().casefold()
                and previous["remote"] == block["remote"]
                and previous.get("room", "") == block.get("room", "")
            )
            if same_session:
                previous["end"] = block["end"]
                continue
        grouped.append(dict(block))
    return grouped


def parse_single_page(text):
    """Wyciąga datę i zajęcia z jednej strony PDF."""
    if not text:
        return None, None

    date_match = re.search(
        r"(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paź|paz|lis|gru)\s+(\d{1,2})\s*,\s*(\d{4})",
        text,
        re.IGNORECASE,
    )
    if not date_match:
        return None, None

    month = MONTHS_MAP[date_match.group(1).lower()]
    day_number = int(date_match.group(2))
    year_number = int(date_match.group(3))
    iso_date = f"{year_number}-{month}-{day_number:02d}"

    pattern = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")
    matches = list(pattern.finditer(text))
    if not matches:
        return iso_date, None

    raw_blocks = []
    for index, match in enumerate(matches):
        start_time = match.group(1).zfill(5)
        end_time = match.group(2).zfill(5)
        chunk_start = match.end()
        chunk_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = " ".join(text[chunk_start:chunk_end].split())

        class_type = "Wykł." if re.search(r"Wyk[łl]ad", chunk, re.I) else "Ćw."
        remote = bool(re.search(r"Zdalnie|Zda\s*dalnie", chunk, re.I))
        room = ""
        if not remote:
            if re.search(r"Br[aą]k\s*sal", chunk, re.I):
                room = "BRAK SALI"
            elif re.search(r"HALA\s*SPORTOWA", chunk, re.I):
                room = "HALA SPORTOWA"
            elif re.search(r"10-BIBLIOTEKA", chunk, re.I):
                room = "10-BIBLIOTEKA"
            elif re.search(r"Aula\s*\d+", chunk, re.I):
                room_match = re.search(r"Aula\s*\d+", chunk, re.I)
                room = room_match.group(0) if room_match else ""
            elif re.search(r"\bH\d+\b", chunk):
                room_match = re.search(r"\bH\d+\b", chunk)
                room = room_match.group(0) if room_match else ""
            else:
                room_match = re.search(r"\b(020|104|105|106|107|11|3)\b", chunk)
                room = room_match.group(1) if room_match else "BRAK SALI"

        lecturer_match = re.search(
            r"((?:prof\.|dr\s+hab\.|dr|mgr|mor|mar)\s+[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż\-]+)",
            chunk,
        )
        lecturer = (
            lecturer_match.group(1).replace("mor ", "mgr ").replace("mar ", "mgr ")
            if lecturer_match else "PANS"
        )
        title = chunk[:lecturer_match.start()] if lecturer_match else chunk
        title = re.sub(r"\bWszyscy\b|\bBezpieczeństwo\s*Narodowe\b", "", title, flags=re.I)
        title = re.sub(r"\s+", " ", title).strip(" .-–")
        if not title:
            title = "Zajęcia kierunkowe BN"

        raw_blocks.append({
            "start": start_time,
            "end": end_time,
            "title": title,
            "lecturer": lecturer,
            "type": class_type,
            "remote": remote,
            "room": room,
        })

    grouped = merge_adjacent_blocks(raw_blocks)
    modes = {item["remote"] for item in grouped}
    day_mode = "MIESZANE" if len(modes) > 1 else ("ZDALNE" if modes == {True} else "STACJONARNE")
    items = []
    for block in grouped:
        item = {
            "time": f'{block["start"]}-{block["end"]}',
            "title": block["title"],
            "lecturer": block["lecturer"],
            "type": block["type"],
            "mode": "ZDALNE" if block["remote"] else "STACJONARNE",
        }
        if not block["remote"]:
            item["room"] = block.get("room") or "BRAK SALI"
        items.append(item)
    return iso_date, {"mode": day_mode, "items": items}


def event_mode(item, day):
    return item.get("mode") or day.get("mode", "STACJONARNE")


def item_fingerprint(item, day):
    return (
        item.get("time", ""),
        item.get("title", "").strip().casefold(),
        item.get("lecturer", "").strip().casefold(),
        item.get("type", "").strip().casefold(),
        event_mode(item, day),
        item.get("room", "").strip().casefold(),
    )


def change_score(old_item, old_day, new_item, new_day):
    score = 0
    if old_item.get("title", "").strip().casefold() == new_item.get("title", "").strip().casefold():
        score += 40
    if old_item.get("lecturer", "").strip().casefold() == new_item.get("lecturer", "").strip().casefold():
        score += 25
    if old_item.get("time", "") == new_item.get("time", ""):
        score += 30
    elif old_item.get("time", "").split("-")[0] == new_item.get("time", "").split("-")[0]:
        score += 18
    if old_item.get("type", "") == new_item.get("type", ""):
        score += 8
    if event_mode(old_item, old_day) == event_mode(new_item, new_day):
        score += 8
    return score


def build_change_notifications(old_days, new_days, update_id, created_at=None):
    """Porównuje plany i zwraca wyłącznie rzeczywiste zmiany w zajęciach."""
    created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    changes = []
    for date in sorted(set(old_days) | set(new_days)):
        old_day = old_days.get(date) or {"mode": "STACJONARNE", "items": []}
        new_day = new_days.get(date) or {"mode": "STACJONARNE", "items": []}
        old_items = list(old_day.get("items") or [])
        new_items = list(new_day.get("items") or [])

        old_remaining = list(range(len(old_items)))
        new_remaining = list(range(len(new_items)))

        # Usuń pozycje identyczne, aby nie generować fałszywych alarmów.
        for old_index in list(old_remaining):
            fingerprint = item_fingerprint(old_items[old_index], old_day)
            match = next((new_index for new_index in new_remaining
                          if item_fingerprint(new_items[new_index], new_day) == fingerprint), None)
            if match is not None:
                old_remaining.remove(old_index)
                new_remaining.remove(match)

        # Dopasuj najbardziej podobne pozostałe pozycje i wykryj zmianę danych.
        candidates = []
        for oi in old_remaining:
            for ni in new_remaining:
                candidates.append((change_score(old_items[oi], old_day, new_items[ni], new_day), oi, ni))
        candidates.sort(reverse=True)
        paired_old, paired_new = set(), set()
        for score, oi, ni in candidates:
            if score < 30 or oi in paired_old or ni in paired_new:
                continue
            paired_old.add(oi)
            paired_new.add(ni)
            old_item, new_item = old_items[oi], new_items[ni]
            details = []
            if old_item.get("time") != new_item.get("time"):
                details.append(f'Godzina: {old_item.get("time", "—")} → {new_item.get("time", "—")}')
            if old_item.get("title") != new_item.get("title"):
                details.append(f'Przedmiot: {old_item.get("title", "—")} → {new_item.get("title", "—")}')
            if old_item.get("lecturer") != new_item.get("lecturer"):
                details.append(f'Prowadzący: {old_item.get("lecturer", "—")} → {new_item.get("lecturer", "—")}')
            if old_item.get("type") != new_item.get("type"):
                details.append(f'Typ zajęć: {old_item.get("type", "—")} → {new_item.get("type", "—")}')
            old_mode, new_mode = event_mode(old_item, old_day), event_mode(new_item, new_day)
            if old_mode != new_mode:
                details.append(f'Tryb: {old_mode} → {new_mode}')
            if old_item.get("room", "") != new_item.get("room", ""):
                details.append(f'Sala: {old_item.get("room") or "—"} → {new_item.get("room") or "—"}')
            if details:
                changes.append({
                    "id": f"{update_id}-{date}-change-{len(changes)+1}",
                    "date": date,
                    "type": "changed",
                    "title": "Zmieniono zajęcia",
                    "message": new_item.get("title") or old_item.get("title") or "Zajęcia",
                    "details": details,
                    "created_at": created_at,
                })

        for oi in old_remaining:
            if oi in paired_old:
                continue
            item = old_items[oi]
            changes.append({
                "id": f"{update_id}-{date}-cancelled-{len(changes)+1}",
                "date": date,
                "type": "cancelled",
                "title": "Odwołano zajęcia",
                "message": item.get("title", "Zajęcia") + " · " + item.get("time", ""),
                "details": [item.get("lecturer", "Prowadzący niepodany")],
                "created_at": created_at,
            })

        for ni in new_remaining:
            if ni in paired_new:
                continue
            item = new_items[ni]
            mode = event_mode(item, new_day)
            details = [item.get("lecturer", "Prowadzący niepodany")]
            details.append("Tryb: " + mode)
            if item.get("room"):
                details.append("Sala: " + item["room"])
            changes.append({
                "id": f"{update_id}-{date}-added-{len(changes)+1}",
                "date": date,
                "type": "added",
                "title": "Dodano nowe zajęcia",
                "message": item.get("title", "Zajęcia") + " · " + item.get("time", ""),
                "details": details,
                "created_at": created_at,
            })
    return changes[:150]


def validate_schedule(days):
    if not days:
        raise RuntimeError("Parser nie odczytał żadnego dnia — poprzedni schedule.json pozostaje bez zmian.")
    for date, day in days.items():
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError(f"Nieprawidłowa data w planie: {date}")
        for item in day.get("items", []):
            start, end = item["time"].split("-", 1)
            if time_to_minutes(start) >= time_to_minutes(end):
                raise ValueError(f"Nieprawidłowy przedział czasu {item['time']} dla {date}")
    print(f"Kontrola danych: {len(days)} dni, {sum(len(d.get('items', [])) for d in days.values())} bloków zajęć.")


def read_json_if_exists(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main():
    url, label = find_bn_resource_link()
    print(f"Pobieranie planu z: {url} ({label})")
    response = requests.get(url, headers=HEADERS, timeout=45, allow_redirects=True)
    response.raise_for_status()
    pdf_bytes = response.content
    current_hash = hashlib.sha256(pdf_bytes).hexdigest()

    if os.path.exists(HASH_FILE) and os.path.exists(OUTPUT_JSON):
        with open(HASH_FILE, "r", encoding="utf-8") as handle:
            if handle.read().strip() == current_hash:
                print("Plik PDF nie zmienił się od ostatniego sprawdzenia.")
                return

    old_payload = read_json_if_exists(OUTPUT_JSON, {"days": {}})
    old_days = old_payload.get("days") or {}
    days_dict = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            iso_date, day_obj = parse_single_page(text)
            if iso_date and day_obj:
                days_dict[iso_date] = day_obj

    validate_schedule(days_dict)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {"last_updated": now, "source_label": label, "days": days_dict}
    changes = build_change_notifications(old_days, days_dict, current_hash[:12], now)
    notifications = {
        "update_id": current_hash[:12],
        "last_updated": now,
        "changes": changes,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    with open(NOTIFICATIONS_JSON, "w", encoding="utf-8") as handle:
        json.dump(notifications, handle, ensure_ascii=False, indent=2)
    with open(HASH_FILE, "w", encoding="utf-8") as handle:
        handle.write(current_hash)

    print(f"Zapisano {len(days_dict)} dni planu. Wykryto {len(changes)} zmian zajęć.")


if __name__ == "__main__":
    main()
