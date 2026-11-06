import hashlib
import io
import json
import os
import re
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import pdfplumber
import requests

COURSE_URL = "https://www.edukacja.pans-koszalin.pl/course/view.php?id=9443"
FALLBACK_RESOURCE_URL = "https://www.edukacja.pans-koszalin.pl/mod/resource/view.php?id=134991"
HASH_FILE = "last_hash.txt"
OUTPUT_JSON = "schedule.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

MONTHS_MAP = {
    "sty": "01",
    "lut": "02",
    "mar": "03",
    "kwi": "04",
    "maj": "05",
    "cze": "06",
    "lip": "07",
    "sie": "08",
    "wrz": "09",
    "paź": "10",
    "paz": "10",
    "lis": "11",
    "gru": "12",
}


def find_bn_resource_link():
    """Przeszukuje stronę PANS Koszalin w poszukiwaniu planu BN 1 stacjonarne."""
    try:
        res = requests.get(COURSE_URL, headers=HEADERS, timeout=25)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        for a in soup.find_all("a", href=True):
            label = " ".join(a.get_text().split()).lower()
            href = a["href"]
            if "mod/resource/view.php" in href and "bn" in label:
                # Wykluczamy studia II stopnia (mgr) oraz niestacjonarne, szukamy BN 1 stacjonarne
                if "mgr" not in label and "niestacjonarne" not in label:
                    return urljoin(COURSE_URL, href), label
    except Exception as e:
        print(f"Ostrzeżenie podczas skanowania kursu: {e}")

    return FALLBACK_RESOURCE_URL, "plan bn 1 stacjonarne (link bezpośredni)"


def parse_single_page(text):
    """Wyciąga datę oraz zgrupowane bloki zajęć z pojedynczej strony PDF."""
    if not text:
        return None, None

    # Normalizacja rozstrzelonego tekstu (np. z niektórych stron PDF)
    cleaned_text = re.sub(r"(?<=\b\w)\s+(?=\w\b)", "", text)

    # Szukamy daty w nagłówku np. 'paź 1, 2026' lub 'sty 10, 2027'
    date_match = re.search(
        r"(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paź|paz|lis|gru)\s+(\d{1,2})\s*,\s*(\d{4})",
        text,
        re.IGNORECASE,
    )
    if not date_match:
        return None, None

    m_str = date_match.group(1).lower()
    day_num = int(date_match.group(2))
    year_num = int(date_match.group(3))
    month_num = MONTHS_MAP.get(m_str, "01")
    iso_date = f"{year_num}-{month_num}-{day_num:02d}"

    # Szukamy wszystkich bloków godzinowych HH:MM-HH:MM
    pattern = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")
    matches = list(pattern.finditer(text))
    if not matches:
        return iso_date, None

    raw_blocks = []
    for idx, match in enumerate(matches):
        start_t = match.group(1).zfill(5)
        end_t = match.group(2).zfill(5)
        chunk_start = match.end()
        chunk_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        chunk = " ".join(text[chunk_start:chunk_end].split())

        # Określenie formy zajęć
        c_type = "Wykł." if re.search(r"Wyk[łl]ad", chunk, re.I) else "Ćw."

        # Określenie trybu i sali
        is_remote = bool(re.search(r"Zdalnie|Zda\s*dalnie", chunk, re.I))
        room = ""
        if not is_remote:
            if re.search(r"Br[aá]k\s*sal", chunk, re.I):
                room = "BRAK SALI"
            elif re.search(r"HALA\s*SPORTOWA", chunk, re.I):
                room = "HALA SPORTOWA"
            elif re.search(r"10-BIBLIOTEKA", chunk, re.I):
                room = "10-BIBLIOTEKA"
            elif re.search(r"Aula\s*\d+", chunk, re.I):
                room = re.search(r"Aula\s*\d+", chunk, re.I).group(0)
            elif re.search(r"\bH\d+\b", chunk):
                room = re.search(r"\bH\d+\b", chunk).group(0)
            else:
                rm = re.search(r"\b(020|104|105|106|107|11|3)\b", chunk)
                room = rm.group(1) if rm else "STACJONARNIE"

        # Wyciągnięcie prowadzącego
        lec_match = re.search(
            r"((?:prof\.|dr\s+hab\.|dr|mgr|mor|mar)\s+[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż\-]+)",
            chunk,
        )
        lecturer = lec_match.group(1).replace("mor ", "mgr ").replace("mar ", "mgr ") if lec_match else "PANS"

        # Wyciągnięcie nazwy przedmiotu (tekst przed nazwiskiem wykładowcy)
        title = chunk
        if lec_match:
            title = chunk[: lec_match.start()]
        title = re.sub(r"\bWszyscy\b|\bBezpieczeństwo\s*Narodowe\b", "", title, flags=re.I).strip(" .-–")
        if not title:
            title = "Zajęcia kierunkowe BN"

        raw_blocks.append(
            {
                "start": start_t,
                "end": end_t,
                "title": title,
                "lecturer": lecturer,
                "type": c_type,
                "remote": is_remote,
                "room": room,
            }
        )

    # Grupowanie sąsiadujących bloków tego samego przedmiotu
    grouped = []
    for b in raw_blocks:
        if grouped and grouped[-1]["title"].lower() == b["title"].lower() and grouped[-1]["lecturer"] == b["lecturer"]:
            grouped[-1]["end"] = b["end"]
            if b["type"] not in grouped[-1]["type"]:
                grouped[-1]["type"] += f"/{b['type']}"
        else:
            grouped.append(b)

    day_mode = "ZDALNE" if all(g["remote"] for g in grouped) else "STACJONARNE"
    items = []
    for g in grouped:
        item = {
            "time": f"{g['start']}-{g['end']}",
            "title": g["title"],
            "lecturer": g["lecturer"],
            "type": g["type"],
        }
        if day_mode == "STACJONARNE":
            item["room"] = g["room"] or "BRAK SALI"
        items.append(item)

    return iso_date, {"mode": day_mode, "items": items}


def main():
    url, label = find_bn_resource_link()
    print(f"Pobieranie planu z: {url} ({label})")

    res = requests.get(url, headers=HEADERS, timeout=45, allow_redirects=True)
    res.raise_for_status()
    pdf_bytes = res.content

    current_hash = hashlib.sha256(pdf_bytes).hexdigest()
    if os.path.exists(HASH_FILE) and os.path.exists(OUTPUT_JSON):
        with open(HASH_FILE, "r", encoding="utf-8") as hf:
            if hf.read().strip() == current_hash:
                print("Plik PDF nie zmienił się od ostatniego sprawdzenia.")
                return

    days_dict = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            iso_date, day_obj = parse_single_page(txt)
            if iso_date and day_obj:
                days_dict[iso_date] = day_obj

    payload = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source_label": label,
        "days": days_dict,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    with open(HASH_FILE, "w", encoding="utf-8") as hf:
        hf.write(current_hash)

    print(f"Zapisano {len(days_dict)} dni z zajęciami do {OUTPUT_JSON}.")


if __name__ == "__main__":
    main()
