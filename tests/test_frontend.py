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

    def test_service_worker_fetches_push_config_from_network_first(self):
        service_worker = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertIn('pans-plan-shell-v3', service_worker)
        self.assertIn('const isPushConfig = url.pathname.endsWith("/push-config.js")', service_worker)
        self.assertIn('new Request(request, { cache: "no-store" })', service_worker)
        self.assertIn('const response = await fetch(liveRequest)', service_worker)

    def test_push_backend_setup_is_documented(self):
        setup = (ROOT / "cloudflare" / "README.md").read_text(encoding="utf-8")
        for value in ("PUSH_WORKER_URL", "PUSH_DISPATCH_TOKEN", "VAPID_PRIVATE_KEY", "PUSH_KV"):
            self.assertIn(value, setup)


if __name__ == "__main__":
    unittest.main()
