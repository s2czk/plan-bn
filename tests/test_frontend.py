import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendChecks(unittest.TestCase):
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
        ):
            self.assertIn(required, html)
        self.assertNotIn(">BN1<", html)

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


if __name__ == "__main__":
    unittest.main()
