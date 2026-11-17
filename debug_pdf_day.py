import re
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup

COURSE_URL = "https://www.edukacja.pans-koszalin.pl/course/view.php?id=9443"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
TARGET = "lis 16, 2026"

response = requests.get(COURSE_URL, headers=HEADERS, timeout=25)
response.raise_for_status()
soup = BeautifulSoup(response.text, "html.parser")
resource_url = None
label = None
for anchor in soup.find_all("a", href=True):
    text = " ".join(anchor.get_text().split()).lower()
    if "mod/resource/view.php" in anchor["href"] and "bn" in text and "mgr" not in text and "niestacjonarne" not in text:
        resource_url = urljoin(COURSE_URL, anchor["href"])
        label = text
        break
if not resource_url:
    raise SystemExit("Nie znaleziono zasobu BN I stacjonarne.")
print("DEBUG_SOURCE", resource_url, label, flush=True)
pdf_response = requests.get(resource_url, headers=HEADERS, timeout=45)
pdf_response.raise_for_status()
with pdfplumber.open(__import__("io").BytesIO(pdf_response.content)) as pdf:
    print("DEBUG_PAGES", len(pdf.pages), flush=True)
    found = 0
    for page_number, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        if re.search(r"lis\\s+16,\\s*2026", text, re.IGNORECASE):
            found += 1
            print(f"DEBUG_PAGE {page_number} size={page.width}x{page.height}", flush=True)
            print("DEBUG_TEXT_BEGIN", flush=True)
            print(page.extract_text(layout=True) or text, flush=True)
            print("DEBUG_TEXT_END", flush=True)
            words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False, use_text_flow=False)
            print("DEBUG_WORDS_BEGIN", flush=True)
            for word in words:
                print(f"{word['top']:.1f}|{word['x0']:.1f}-{word['x1']:.1f}|{word['text']}", flush=True)
            print("DEBUG_WORDS_END", flush=True)
    print("DEBUG_MATCHED_PAGES", found, flush=True)
