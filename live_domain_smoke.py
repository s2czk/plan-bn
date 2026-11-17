import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin

import requests

BASE = "https://plan.mandaro.eu/"
HEADERS = {
    "Cache-Control": "no-cache, no-store, max-age=0",
    "Pragma": "no-cache",
    "User-Agent": "Mandaro-Live-Smoke-Test/1.0",
}

session = requests.Session()
session.headers.update(HEADERS)

def fetch(path):
    url = urljoin(BASE, path)
    response = session.get(url, timeout=25, allow_redirects=True)
    response.raise_for_status()
    print(json.dumps({
        "requested": url,
        "final_url": response.url,
        "status": response.status_code,
        "bytes": len(response.content),
        "cf_cache_status": response.headers.get("CF-Cache-Status"),
        "age": response.headers.get("Age"),
        "etag": response.headers.get("ETag"),
        "cache_control": response.headers.get("Cache-Control"),
    }, ensure_ascii=False))
    return response

local_html = Path("index.html").read_bytes()
local_sw = Path("sw.js").read_text(encoding="utf-8")
local_schedule = json.loads(Path("schedule.json").read_text(encoding="utf-8"))

live_html_response = fetch("index.html?smoke=20261117")
live_html = live_html_response.content.decode("utf-8", errors="replace")
live_sw_response = fetch("sw.js?smoke=20261117")
live_sw = live_sw_response.text
live_schedule_response = fetch("schedule.json?smoke=20261117")
live_schedule = live_schedule_response.json()

checks = {
    "html_hash_matches_repo": hashlib.sha256(live_html_response.content).hexdigest() == hashlib.sha256(local_html).hexdigest(),
    "click_handler_uses_own_date": "selectedDateChange(dayISO)" in live_html,
    "live_sw_cache_matches_repo": (local_sw.splitlines()[0] if local_sw.splitlines() else "") == (live_sw.splitlines()[0] if live_sw.splitlines() else ""),
    "tuesday_17_schedule_matches_repo": live_schedule.get("days", {}).get("2026-11-17") == local_schedule.get("days", {}).get("2026-11-17"),
    "tuesday_17_exists": bool(live_schedule.get("days", {}).get("2026-11-17", {}).get("items")),
}
print(json.dumps({
    "live_domain": BASE,
    "repo_html_sha256": hashlib.sha256(local_html).hexdigest(),
    "live_html_sha256": hashlib.sha256(live_html_response.content).hexdigest(),
    "repo_sw_cache": local_sw.splitlines()[0] if local_sw.splitlines() else "",
    "live_sw_cache": live_sw.splitlines()[0] if live_sw.splitlines() else "",
    "checks": checks,
    "live_tuesday_17": live_schedule.get("days", {}).get("2026-11-17"),
}, ensure_ascii=False, indent=2))
if not all(checks.values()):
    raise SystemExit("Domena nie serwuje zgodnej wersji strony/planu — sprawdź wynik powyżej.")
