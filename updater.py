import hashlib
import io
import json
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup

COURSE_URL = "https://www.edukacja.pans-koszalin.pl/course/view.php?id=9443"
FALLBACK_RESOURCE_URL = "https://www.edukacja.pans-koszalin.pl/mod/resource/view.php?id=134991"
HASH_FILE = "last_hash.txt"
OUTPUT_JSON = "schedule.json"
NOTIFICATIONS_JSON = "notifications.json"
PUSH_PAYLOAD_FILE = "push_payload.json"
PENDING_PUSH_FILE = "pending_push.json"
UPDATE_SEQUENCE_FILE = "update_sequence.txt"
PARSER_VERSION_FILE = "parser_version.txt"
PARSER_VERSION = "4"
WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def local_now():
    """Zwraca lokalny czas Warszawy jako naiwny datetime do istniejącego formatu JSON."""
    return datetime.now(WARSAW_TZ).replace(tzinfo=None)

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


def clean_subject_title(value):
    """Usuwa z końca tytułu techniczne dopiski PDF: godziny, typ zajęć, grupę i rok."""
    title = str(value or "")
    title = re.sub(r"\b\d{1,2}:\d{2}\b", " ", title)
    title = re.sub(r"\b(?:grupa|gr\.?)\s*[A-Za-z0-9IVX/-]+\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\([^)]*\b20\d{2}\s*/\s*20\d{2}\b[^)]*\)\s*$", "", title, flags=re.IGNORECASE)

    type_suffix = re.search(
        r"\s*(?:[-–—]\s*)?(?:wykład|wykł\.?|wykładowy|ćwiczenia|ćwiczeń|ćw\.?)"
        r"(?:\s+[IVXLCDM]+)?\s*$",
        title,
        flags=re.IGNORECASE,
    )
    if type_suffix:
        title = title[:type_suffix.start()]
        # PDF occasionally places a room number directly before the class type.
        title = re.sub(
            r"\s+(?:020|104|105|106|107|11|3|H\d{1,3}|aula\s*\d+|10-biblioteka|hala\s+sportowa|brak\s+sal(?:i|ę))\s*$",
            "",
            title,
            flags=re.IGNORECASE,
        )

    title = re.sub(r"\s+(?:zdalnie|zda\s*dalnie|stacjonarnie)\s*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" .-–—,:;")
    return title or "Zajęcia kierunkowe BN"


def normalize_subject_title(value):
    """Porównawcza nazwa przedmiotu niezależna od typu zajęć i numeru grupy."""
    title = clean_subject_title(value).casefold()
    return re.sub(r"[^0-9a-ząćęłńóśźż]+", " ", title).strip()


def unique_values(values):
    result = []
    seen = set()
    for value in values:
        value = str(value or "").strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def extract_group_labels(text):
    groups = []
    for match in re.finditer(r"\b(?:grupa|gr\.?)\s*((?:[A-Z]?\d+[A-Z]?(?:[/,-][A-Z]?\d+[A-Z]?)?|[IVX]{1,4}|[A-Z]))\b", text or "", re.IGNORECASE):
        groups.append("grupa " + match.group(1))
    return unique_values(groups)


def extract_class_types(text):
    labels = []
    if re.search(r"\bwyk[łl](?:ad|\.?)", text or "", re.IGNORECASE):
        labels.append("wykład")
    if re.search(r"\b(?:ćwiczen\w*|ćw\.?)", text or "", re.IGNORECASE):
        labels.append("ćwiczenia")
    return labels or ["zajęcia"]


def merge_adjacent_blocks(raw_blocks):
    """Scalaj kolejne wystąpienia tego samego przedmiotu; przerwy i metadane nie rozdzielają bloku."""
    ordered = sorted(raw_blocks, key=lambda item: time_to_minutes(item["start"]))
    grouped = []

    for block in ordered:
        detected_groups = unique_values(extract_group_labels(block.get("title", "")) + [block.get("group", "")])
        title = clean_subject_title(block.get("title"))
        key = normalize_subject_title(title)
        if grouped and normalize_subject_title(grouped[-1]["title"]) == key:
            current = grouped[-1]
            if time_to_minutes(block["end"]) > time_to_minutes(current["end"]):
                current["end"] = block["end"]
            current["_lecturers"] = unique_values(current["_lecturers"] + [block.get("lecturer", "")])
            current["_types"] = unique_values(current["_types"] + [block.get("type", "")])
            current["_groups"] = unique_values(current["_groups"] + detected_groups)
            current["_rooms"] = unique_values(current["_rooms"] + [block.get("room", "")])
            current["_modes"] = unique_values(current["_modes"] + ["ZDALNE" if block.get("remote") else "STACJONARNE"])
        else:
            grouped.append({
                "start": block["start"],
                "end": block["end"],
                "title": title,
                "_lecturers": unique_values([block.get("lecturer", "")]),
                "_types": unique_values([block.get("type", "")]),
                "_groups": detected_groups,
                "_rooms": unique_values([block.get("room", "")]),
                "_modes": ["ZDALNE" if block.get("remote") else "STACJONARNE"],
            })

    result = []
    for block in grouped:
        modes = block.pop("_modes")
        lecturers = block.pop("_lecturers")
        types = block.pop("_types")
        groups = block.pop("_groups")
        rooms = block.pop("_rooms")
        block["lecturer"] = " / ".join(lecturers) or "PANS"
        block["type"] = " / ".join(types) or "zajęcia"
        block["group"] = " / ".join(groups)
        block["room"] = " / ".join(rooms)
        block["mode"] = modes[0] if len(modes) == 1 else "MIESZANE"
        result.append(block)
    return result

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
    datetime.strptime(iso_date, "%Y-%m-%d")

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

        class_types = extract_class_types(chunk)
        groups = extract_group_labels(chunk)
        remote = bool(re.search(r"Zdalnie|Zda\s*dalnie", chunk, re.IGNORECASE))

        lecturer_match = re.search(
            r"((?:prof\.|dr\s+hab\.|dr|mgr|mor|mar)\s+[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż\-]+)",
            chunk,
            re.IGNORECASE,
        )
        lecturer = (
            lecturer_match.group(1).replace("mor ", "mgr ").replace("mar ", "mgr ")
            if lecturer_match else "PANS"
        )

        title_source = chunk[:lecturer_match.start()] if lecturer_match else chunk
        title = clean_subject_title(title_source)
        title = re.sub(r"\bWszyscy\b|\bBezpieczeństwo\s*Narodowe\b", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s+", " ", title).strip(" .-–—")
        if not title:
            title = "Zajęcia kierunkowe BN"

        room = ""
        if not remote:
            # Godziny w tekście PDF nie mogą zostać błędnie odczytane jako numer sali.
            room_text = re.sub(r"\b\d{1,2}:\d{2}\b", " ", chunk)
            if re.search(r"Br[aą]k\s*sal", room_text, re.IGNORECASE):
                room = "BRAK SALI"
            elif re.search(r"HALA\s*SPORTOWA", room_text, re.IGNORECASE):
                room = "HALA SPORTOWA"
            elif re.search(r"10-BIBLIOTEKA", room_text, re.IGNORECASE):
                room = "10-BIBLIOTEKA"
            elif re.search(r"Aula\s*\d+", room_text, re.IGNORECASE):
                room_match = re.search(r"Aula\s*\d+", room_text, re.IGNORECASE)
                room = room_match.group(0) if room_match else ""
            elif re.search(r"\bH\d+\b", room_text):
                room_match = re.search(r"\bH\d+\b", room_text)
                room = room_match.group(0) if room_match else ""
            else:
                room_match = re.search(r"\b(020|104|105|106|107|11|3)\b", room_text)
                room = room_match.group(1) if room_match else "BRAK SALI"

        raw_blocks.append({
            "start": start_time,
            "end": end_time,
            "title": title,
            "lecturer": lecturer,
            "type": " / ".join(class_types),
            "group": " / ".join(groups),
            "remote": remote,
            "room": room,
        })

    grouped = merge_adjacent_blocks(raw_blocks)
    modes = {item["mode"] for item in grouped}
    day_mode = "MIESZANE" if len(modes) > 1 or "MIESZANE" in modes else (next(iter(modes)) if modes else "STACJONARNE")
    items = []
    for block in grouped:
        item = {
            "time": f'{block["start"]}-{block["end"]}',
            "title": block["title"],
            "lecturer": block["lecturer"],
            "type": block["type"],
            "mode": block["mode"],
        }
        if block.get("group"):
            item["group"] = block["group"]
        if block.get("room"):
            item["room"] = block["room"]
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
        item.get("group", "").strip().casefold(),
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
    if old_item.get("group", "").strip().casefold() == new_item.get("group", "").strip().casefold():
        score += 8
    if event_mode(old_item, old_day) == event_mode(new_item, new_day):
        score += 8
    return score


def build_change_notifications(old_days, new_days, update_id, created_at=None):
    """Porównuje plany i zwraca wyłącznie rzeczywiste zmiany w zajęciach."""
    created_at = created_at or local_now().strftime("%Y-%m-%d %H:%M")
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
            if old_item.get("group", "") != new_item.get("group", ""):
                details.append(f'Grupa: {old_item.get("group") or "—"} → {new_item.get("group") or "—"}')
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
                "details": [item.get("lecturer", "Prowadzący niepodany")] + (["Grupa: " + item["group"]] if item.get("group") else []),
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
            if item.get("group"):
                details.append("Grupa: " + item["group"])
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


def group_change_notifications(changes, update_id, created_at):
    """Grupuje wszystkie wykryte zmiany z jednego dnia w jeden komunikat."""
    grouped = {}
    for change in changes:
        grouped.setdefault(change.get("date", ""), []).append(change)

    summaries = []
    for date, events in sorted(grouped.items()):
        count = len(events)
        count_text = f"Wykryto {count} zmianę" if count == 1 else (
            f"Wykryto {count} zmiany" if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14
            else f"Wykryto {count} zmian"
        )
        push_labels = {"added": "DODANO", "cancelled": "USUNIĘTO", "changed": "ZMIENIONO"}
        push_parts = []
        for event in events:
            label = push_labels.get(event.get("type"), "ZMIANA")
            part = f"{label}: {event.get('message') or event.get('title') or 'Zajęcia'}"
            details = "; ".join(event.get("details") or [])
            if details:
                part += " — " + details
            push_parts.append(part)

        summaries.append({
            "id": f"{update_id}-{date}",
            "date": date,
            "type": "summary",
            "title": "Zmiany w planie zajęć",
            "message": count_text + " w planie zajęć.",
            "push_message": (count_text + ": " + " | ".join(push_parts))[:3000],
            "events": events,
            "created_at": created_at,
            "url": f"./?date={date}",
        })
    return summaries


def keep_recent_notifications(notifications, now=None):
    """Pozostawia tylko siedmiodniową historię powiadomień."""
    now = now or local_now()
    cutoff = now - timedelta(days=7)
    kept = []
    seen = set()
    for item in notifications or []:
        try:
            created = datetime.strptime(item.get("created_at", ""), "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            continue
        if created < cutoff or created > now + timedelta(days=1):
            continue
        identifier = item.get("id")
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        kept.append(item)
    return sorted(kept, key=lambda item: item.get("created_at", ""))


def validate_schedule(days):
    if not days:
        raise RuntimeError("Parser nie odczytał żadnego dnia — poprzedni schedule.json pozostaje bez zmian.")
    for date, day in days.items():
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError(f"Nieprawidłowa data w planie: {date}")
        datetime.strptime(date, "%Y-%m-%d")
        for item in day.get("items", []):
            if not item.get("title", "").strip():
                raise ValueError(f"Brak nazwy przedmiotu dla {date}")
            start, end = item["time"].split("-", 1)
            if time_to_minutes(start) >= time_to_minutes(end):
                raise ValueError(f"Nieprawidłowy przedział czasu {item['time']} dla {date}")
    print(f"Kontrola danych: {len(days)} dni, {sum(len(d.get('items', [])) for d in days.values())} bloków zajęć.")

def read_json_if_exists(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(path, payload):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def write_push_payload(notifications):
    write_json_atomic(PUSH_PAYLOAD_FILE, {"notifications": notifications})


def merge_pending_notifications(pending, new_notifications):
    """Zachowuje wszystkie niewysłane powiadomienia i scala je bez duplikowania ID."""
    merged = []
    seen_ids = set()
    for notification in list(pending or []) + list(new_notifications or []):
        if not isinstance(notification, dict):
            raise ValueError("Nieprawidłowa pozycja w kolejce powiadomień Push.")
        identifier = notification.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("Każde powiadomienie Push musi mieć niepuste ID.")
        if identifier not in seen_ids:
            seen_ids.add(identifier)
            merged.append(notification)
    return merged


def read_pending_notifications():
    payload = read_json_if_exists(PENDING_PUSH_FILE, {"notifications": []})
    if not isinstance(payload, dict) or not isinstance(payload.get("notifications", []), list):
        raise ValueError("Plik pending_push.json ma nieprawidłowy format.")
    return payload.get("notifications", [])


def write_pending_notifications(notifications, updated_at=None):
    payload = {"notifications": notifications}
    if updated_at:
        payload["updated_at"] = updated_at
    write_json_atomic(PENDING_PUSH_FILE, payload)


def main():
    parser_version = ""
    if os.path.exists(PARSER_VERSION_FILE):
        with open(PARSER_VERSION_FILE, "r", encoding="utf-8") as handle:
            parser_version = handle.read().strip()
    parser_changed = parser_version != PARSER_VERSION

    url, label = find_bn_resource_link()
    print(f"Pobieranie planu z: {url} ({label})")
    response = requests.get(url, headers=HEADERS, timeout=45, allow_redirects=True)
    response.raise_for_status()
    pdf_bytes = response.content
    if b"%PDF-" not in pdf_bytes[:1024]:
        raise RuntimeError("Pobrany zasób nie wygląda na plik PDF — poprzedni plan pozostaje bez zmian.")
    current_hash = hashlib.sha256(pdf_bytes).hexdigest()

    old_hash = ""
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, "r", encoding="utf-8") as handle:
            old_hash = handle.read().strip()

    try:
        with open(UPDATE_SEQUENCE_FILE, "r", encoding="utf-8") as handle:
            update_sequence = max(0, int(handle.read().strip() or "0"))
    except (OSError, ValueError):
        update_sequence = 0

    if old_hash and old_hash != current_hash:
        update_sequence += 1
    transition_id = f"{update_sequence}-{current_hash[:12]}"

    if old_hash == current_hash and not parser_changed and os.path.exists(OUTPUT_JSON):
        print("PDF i wersja parsera nie zmieniły się — pomijam przetwarzanie.")
        pending_notifications = read_pending_notifications()
        write_pending_notifications(pending_notifications)
        write_push_payload(pending_notifications)
        existing = read_json_if_exists(NOTIFICATIONS_JSON, {"changes": []})
        existing_changes = existing.get("changes", [])
        recent_changes = keep_recent_notifications(existing_changes, local_now())
        if len(recent_changes) != len(existing_changes):
            existing["changes"] = recent_changes
            write_json_atomic(NOTIFICATIONS_JSON, existing)
        return

    old_payload = read_json_if_exists(OUTPUT_JSON, {"days": {}})
    old_days = old_payload.get("days") or {}
    days_dict = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            iso_date, day_obj = parse_single_page(page_text)
            if iso_date and day_obj:
                days_dict[iso_date] = day_obj

    validate_schedule(days_dict)
    now = local_now()
    now_text = now.strftime("%Y-%m-%d %H:%M")
    payload = {"last_updated": now_text, "source_label": label, "days": days_dict}

    # Zmiana samego parsera nie jest zmianą planu. Jeśli równocześnie zmienił się PDF,
    # porównujemy jednak stary i nowy plan, aby nie zgubić prawdziwej aktualizacji.
    previous = read_json_if_exists(NOTIFICATIONS_JSON, {"changes": []})
    history = keep_recent_notifications(previous.get("changes", []), now)
    parser_only_refresh = parser_changed and old_hash == current_hash
    if parser_only_refresh or not old_days or not old_hash:
        current_notifications = []
        print("Przeliczenie parsera / inicjalizacja danych — bez powiadomienia o zmianach.")
    else:
        raw_changes = build_change_notifications(old_days, days_dict, transition_id, now_text)
        current_notifications = group_change_notifications(raw_changes, transition_id, now_text)

    known_ids = {item.get("id") for item in history}
    history.extend(item for item in current_notifications if item.get("id") not in known_ids)
    history = keep_recent_notifications(history, now)

    notifications = {
        "schema_version": 1,
        "update_id": transition_id,
        "last_updated": now_text,
        "changes": history,
    }

    pending_notifications = merge_pending_notifications(
        read_pending_notifications(),
        current_notifications,
    )
    write_pending_notifications(pending_notifications, now_text)

    write_json_atomic(OUTPUT_JSON, payload)
    write_json_atomic(NOTIFICATIONS_JSON, notifications)
    write_push_payload(pending_notifications)
    with open(HASH_FILE + ".tmp", "w", encoding="utf-8") as handle:
        handle.write(current_hash)
    os.replace(HASH_FILE + ".tmp", HASH_FILE)
    with open(PARSER_VERSION_FILE + ".tmp", "w", encoding="utf-8") as handle:
        handle.write(PARSER_VERSION)
    os.replace(PARSER_VERSION_FILE + ".tmp", PARSER_VERSION_FILE)
    with open(UPDATE_SEQUENCE_FILE + ".tmp", "w", encoding="utf-8") as handle:
        handle.write(str(update_sequence))
    os.replace(UPDATE_SEQUENCE_FILE + ".tmp", UPDATE_SEQUENCE_FILE)

    total_items = sum(len(day.get("items", [])) for day in days_dict.values())
    print(f"Zapisano {len(days_dict)} dni i {total_items} bloków. Nowe powiadomienia: {len(current_notifications)}.")


if __name__ == "__main__":
    main()
