import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendChecks(unittest.TestCase):
    def test_python_dependencies_file_exists_and_is_used(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        for package in ("requests", "beautifulsoup4", "pdfplumber"):
            self.assertRegex(requirements, rf"(?m)^{package}([<=>!~]|$)")
        schedule_workflow = (ROOT / ".github" / "workflows" / "update_schedule.yml").read_text(encoding="utf-8")
        tests_workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        for workflow in (schedule_workflow, tests_workflow):
            self.assertIn("cache-dependency-path: requirements.txt", workflow)
            self.assertIn("python -m pip install -r requirements.txt", workflow)

    def test_manifest_is_valid_and_pwa_ready(self):
        manifest = json.loads((ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["background_color"], "#0D1630")
        self.assertEqual(manifest["theme_color"], "#0D1630")
        self.assertTrue(manifest["start_url"])
        self.assertTrue(manifest["icons"])

    def test_page_contains_requested_layout_and_author(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        for required in (
            "linear-gradient(180deg,#0D1630 0%,#17386D 100%)",
            "Bezpieczeństwo Narodowe",
            "weekStrip",
            "weekGrid",
            "monthGrid",
            "szymon@mandaro.eu",
            "notifications.json",
            "Włącz powiadomienia",
            "push-config.js",
            "STACJONARNE",
            "ZDALNE",
        ):
            self.assertIn(required, html)
        self.assertNotIn(">BN1<", html)

    def test_search_is_global_and_not_embedded_in_main_toolbar(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="openSearchFromMonth"', html)
        self.assertIn('id="searchOverlay"', html)
        self.assertIn('id="globalSearchInput"', html)
        self.assertIn("function searchPlan(query)", html)
        self.assertNotIn('id="subjectSearch"', html)
        self.assertNotIn('id="openFilters"', html)
        toolbar = html.split('<div class="toolbar action-toolbar">', 1)[1].split("</div>", 1)[0]
        self.assertNotIn("search-box", toolbar)

    def test_week_view_hides_day_navigation_and_uses_compact_week_toolbar(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="dayNavigation"', html)
        self.assertIn("$('dayNavigation').hidden=view!=='day'", html)
        self.assertIn('class="week-nav"', html)
        self.assertIn("week-nav-button", html)
        self.assertIn("week-download", html)
        self.assertIn('white-space:nowrap;font-size:12px', html)

    def test_open_notification_restores_day_navigation(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("state.view='day';$('dayNavigation').hidden=false", html)

    def test_global_header_search_and_icon_only_day_actions(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="openGlobalSearch"', html)
        self.assertIn('id="copyDay"', html)
        self.assertIn('id="downloadDay"', html)
        self.assertIn('aria-label="Kopiuj plan dnia"', html)
        self.assertIn('aria-label="Pobierz plan dnia jako TXT"', html)
        self.assertNotIn('id="openSearchFromMonth"', html)
        self.assertNotIn("Kopiuj TXT", html)
        self.assertNotIn("Pobierz .txt", html)

    def test_global_subject_search_groups_all_matching_dates(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("const groups=new Map()", html)
        self.assertIn("group.occurrences.forEach", html)
        self.assertIn("search-occurrence-date", html)
        self.assertIn("search-occurrence-time", html)
        self.assertIn("weekdays[parseISO(date).getDay()]", html)

    def test_every_javascript_element_reference_exists(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        defined_ids = set(re.findall(r'\bid="([^"]+)"', html))
        referenced_ids = set(re.findall(r"\$\('([^']+)'\)", html))
        missing = sorted(referenced_ids - defined_ids)
        self.assertFalse(missing, f"JavaScript references missing DOM IDs: {missing}")

    def test_inline_javascript_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed in this environment")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
        self.assertTrue(scripts, "Brak skryptu aplikacji w index.html")
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "app.js"
            script_path.write_text("\n".join(scripts), encoding="utf-8")
            subprocess.run([node, "--check", str(script_path)], check=True, capture_output=True, text=True)

    def test_cloudflare_worker_syntax_and_config(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed in this environment")
        worker = ROOT / "cloudflare" / "src" / "index.js"
        subprocess.run([node, "--check", str(worker)], check=True, capture_output=True, text=True)
        config = (ROOT / "cloudflare" / "wrangler.toml").read_text(encoding="utf-8")
        self.assertIn('binding = "PUSH_KV"', config)
        self.assertIn('name = "plan-bn-push"', config)
        self.assertIn('previews = { }', config)

        package_data = json.loads((ROOT / "cloudflare" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package_data["scripts"]["deploy"], "wrangler deploy")
        self.assertEqual(package_data["scripts"]["preview"], "wrangler preview")
        self.assertEqual(package_data["devDependencies"]["wrangler"], "4.158.0")
        self.assertGreaterEqual(int(package_data["engines"]["node"].replace(">=", "")), 22)

    def test_service_worker_fetches_push_config_from_network_first(self):
        service_worker = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertIn('pans-plan-shell-v4', service_worker)
        self.assertIn('const isNavigation = request.mode === "navigate" || url.pathname.endsWith("/index.html")', service_worker)
        self.assertIn('const liveRequest = new Request(request, { cache: "no-store" })', service_worker)
        self.assertIn('const isPushConfig = url.pathname.endsWith("/push-config.js")', service_worker)
        self.assertIn('new Request(request, { cache: "no-store" })', service_worker)
        self.assertIn('const response = await fetch(liveRequest)', service_worker)

    def test_push_backend_setup_is_documented(self):
        setup = (ROOT / "cloudflare" / "README.md").read_text(encoding="utf-8")
        for value in ("PUSH_WORKER_URL", "PUSH_DISPATCH_TOKEN", "VAPID_PRIVATE_KEY", "PUSH_KV",
                      "Root directory", "npm install --no-audit --no-fund",
                      "npm run deploy", "Enable Preview Builds"):
            self.assertIn(value, setup)


if __name__ == "__main__":
    unittest.main()
