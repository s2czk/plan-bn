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

    def test_fluid_color_theme_is_defined_and_accessible(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("--remote:#c7ef7b", html)
        self.assertIn("--onsite:#59d3e5", html)
        self.assertIn("--purple:#a78bfa", html)
        self.assertIn(".class-card.cancelled{", html)
        self.assertIn(".class-card.cancelled:before", html)
        self.assertIn("color:#f4f7ff", html)
        self.assertIn('<meta name="theme-color" content="#071326">', html)
        self.assertIn("backdrop-filter:blur(20px) saturate(135%)", html)

    def test_neon_aurora_visual_quality_tokens_are_present(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        for token in (
            "rgba(21,39,68,.76)",
            "rgba(8,20,39,.78)",
            ".dashboard-overview",
            ".dashboard-next",
            ".dashboard-stat",
            "box-shadow:inset 0 1px 0 rgba(255,255,255,.055)",
            ".class-card.cancelled:before",
        ):
            self.assertIn(token, html)

    def test_manifest_is_valid_and_pwa_ready(self):
        manifest = json.loads((ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["background_color"], "#050a16")
        self.assertEqual(manifest["theme_color"], "#071326")
        self.assertTrue(manifest["start_url"])
        self.assertTrue(manifest["icons"])

    def test_page_contains_requested_layout_and_author(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        for required in (
            "Plan zajęć",
            'id="dashboardOverview"',
            'id="dashboardNextCard"',
            'id="dashboardActiveCount"',
            "linear-gradient(155deg,#050a16 0%,#08152a 48%,#0a1b34 100%)",
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
        self.assertIn('id="openGlobalSearch"', html)
        self.assertIn('id="searchOverlay"', html)
        self.assertIn('id="globalSearchInput"', html)
        self.assertIn("function searchPlan(query)", html)
        self.assertIn("group.occurrences.forEach", html)
        self.assertNotIn('id="openSearchFromMonth"', html)
        self.assertNotIn('id="subjectSearch"', html)
        self.assertNotIn('id="openFilters"', html)
        header = html.split('<header class="topbar surface">', 1)[1].split("</header>", 1)[0]
        self.assertIn('id="openGlobalSearch"', header)
        self.assertNotIn('id="subjectSearch"', header)

    def test_week_view_hides_day_navigation_and_uses_compact_week_toolbar(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="dayNavigation"', html)
        self.assertIn("$('dayNavigation').hidden=view!=='day'", html)
        self.assertIn('class="week-nav"', html)
        self.assertIn("week-nav-button", html)
        self.assertIn("week-download", html)
        self.assertIn('white-space:nowrap;font-size:12px', html)

    def test_mobile_week_view_stacks_all_seven_days_without_horizontal_scrolling(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(".week-grid{grid-template-columns:minmax(0,1fr);gap:9px}", html)
        self.assertIn(".week-view-scroll{overflow-x:visible;overflow-y:visible;padding-bottom:0}", html)
        self.assertIn(".week-day-header{display:flex;align-items:center;justify-content:space-between", html)

    def test_default_date_stays_on_today_until_midnight(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        match = re.search(r"function defaultSelectedISODate\(now=new Date\(\)\)\{.*?\n    \}", html, re.S)
        self.assertIsNotNone(match, "Brak funkcji wyboru domyślnej daty")
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed in this environment")
        script = match.group(0) + """
console.log(defaultSelectedISODate(new Date(2026, 10, 15, 14, 47)));
console.log(defaultSelectedISODate(new Date(2026, 10, 15, 19, 31)));
console.log(defaultSelectedISODate(new Date(2026, 10, 16, 0, 1)));
"""
        result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip().splitlines(), [
            "2026-11-15",
            "2026-11-15",
            "2026-11-16",
        ])

    def test_day_chip_captures_its_own_date_when_clicked(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        strip = re.search(r"function renderWeekStrip\(\)\{.*?\n    \}", html, re.S)
        self.assertIsNotNone(strip)
        code = strip.group(0)
        self.assertIn("const dayISO=iso", code)
        self.assertIn("btn.addEventListener('click',()=>selectedDateChange(btn.dataset.date))", code)
        self.assertNotIn("btn.addEventListener('click',()=>selectedDateChange(iso))", code)
        self.assertIn("btn.dataset.date=dayISO", code)

    def test_clicking_tuesday_17_renders_only_its_own_schedule(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        schedule = json.loads((ROOT / "schedule.json").read_text(encoding="utf-8"))
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed in this environment")

        selected = re.search(r"function selectedDateChange\(iso\)[^\n]*", html)
        strip = re.search(r"function renderWeekStrip\(\)\{.*?\n    \}", html, re.S)
        day = re.search(r"function renderDay\(\)\{.*?\n    \}", html, re.S)
        day_data = re.search(r"function dayData\(iso\)\{.*?\}", html)
        item_mode = re.search(r"function itemMode\(item,day\)\{.*?\}", html)
        filtered = re.search(r"function filteredItems\(day\)\{.*?\}", html)
        is_cancelled = re.search(r"function isCancelledItem\(item\)\{.*?\}", html)
        parse_iso = re.search(r"function parseISO\(iso\)\{.*?\}", html)
        add_days = re.search(r"function addDays\(iso,n\)\{.*?\}", html)
        iso_date = re.search(r"function isoDate\(d\)\{.*?\}", html)
        polish_date = re.search(r"function polishDate\(iso\)\{.*?\}", html)
        weekdays = re.search(r"const weekdays=\[[^;]+;", html)
        weekdays_short = re.search(r"const weekdaysShort=\[[^;]+;", html)

        for name, match in (
            ("selectedDateChange", selected), ("renderWeekStrip", strip), ("renderDay", day),
            ("dayData", day_data), ("itemMode", item_mode), ("filteredItems", filtered),
            ("isCancelledItem", is_cancelled), ("parseISO", parse_iso), ("addDays", add_days), ("isoDate", iso_date), ("polishDate", polish_date),
            ("weekdays", weekdays), ("weekdaysShort", weekdays_short),
        ):
            self.assertIsNotNone(match, f"Brak funkcji/stałej {name}")

        fixture = json.dumps({date: schedule["days"][date] for date in ("2026-11-16", "2026-11-17")}, ensure_ascii=False)
        script = r'''
const state = {
  selectedDate: "2026-11-16",
  hasUserSelectedDate: false,
  month: 10,
  days: FIXTURE,
  isLoading: false,
  loadError: false
};
const dayCount = {textContent: ""};
const dayClasses = {innerHTML: ""};
const container = {children: [], clientWidth: 1200, scrollLeft: 0};
Object.defineProperty(container, "innerHTML", {
  get() { return ""; },
  set(_) { this.children = []; }
});
container.append = function(button) {
  button.offsetLeft = this.children.length * 68;
  button.offsetWidth = 60;
  this.children.push(button);
};
container.querySelector = function(selector) {
  if (selector !== ".date-chip.active") return null;
  return this.children.find(button => button.className.includes("active")) || null;
};
function $(id) {
  if (id === "weekStrip") return container;
  if (id === "dayCount") return dayCount;
  if (id === "dayClasses") return dayClasses;
  throw new Error("Unexpected DOM id: " + id);
}
global.window = {scrollTo() {}};
global.document = {
  createElement() {
    return {
      dataset: {},
      className: "",
      innerHTML: "",
      offsetLeft: 0,
      offsetWidth: 0,
      setAttribute() {},
      addEventListener(name, callback) { if (name === "click") this.click = callback; },
      append() {}
    };
  }
};
function classCard(item) {
  return item.time + "|" + item.title + "\\n";
}
function renderUpcomingLessons() {}
function renderAll() { renderWeekStrip(); renderDay(); }
''' .replace("FIXTURE", fixture) + "\n" + "\n".join(
            match.group(0) for match in (
                parse_iso, add_days, iso_date, polish_date, day_data, item_mode, filtered,
                weekdays, weekdays_short, selected, strip, day, is_cancelled
            )
        ) + r'''
renderAll();
const tuesday = container.children.find(button => button.dataset.date === "2026-11-17");
if (!tuesday) throw new Error("Nie znaleziono przycisku dla 17.11.2026");
tuesday.click();
const renderedItems = dayClasses.innerHTML.trim().split("\\n").filter(Boolean).map(row => { const [time, title] = row.split("|"); return {time, title}; });
console.log(JSON.stringify({
  selectedDate: state.selectedDate,
  buttonDate: tuesday.dataset.date,
  dayCount: dayCount.textContent,
  renderedItems
}));
'''
        result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
        output = json.loads(result.stdout)
        self.assertEqual(output["selectedDate"], "2026-11-17")
        self.assertEqual(output["buttonDate"], "2026-11-17")
        self.assertEqual(output["dayCount"], "2 zajęcia")
        self.assertEqual(
            output["renderedItems"],
            [
                {"time": "16:45-18:15", "title": "Elementy samoobrony"},
                {"time": "18:30-19:15", "title": "Elementy samoobrony"},
            ],
        )

    def test_cancelled_classes_render_red_and_are_not_counted_as_normal_lessons(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        source_day = {
            "mode": "STACJONARNE",
            "items": [
                {"time": "15:00-15:45", "title": "Podstawy ekonomii", "lecturer": "dr Małgorzata Guziń",
                 "type": "ćwiczenia", "mode": "STACJONARNE", "status": "ODWOŁANE",
                 "status_reason": "Zwolnienie lekarskie", "status_source": "PDF_TEXT_AND_RED_FRAME"},
                {"time": "15:45-16:30", "title": "Podstawy ekonomii", "lecturer": "dr Małgorzata Guziń",
                 "type": "ćwiczenia", "mode": "STACJONARNE", "status": "ODWOŁANE",
                 "status_reason": "Zwolnienie lekarskie", "status_source": "PDF_TEXT_AND_RED_FRAME"},
                {"time": "16:45-17:30", "title": "Podstawy ekonomii", "lecturer": "dr Małgorzata Guziń",
                 "type": "ćwiczenia", "mode": "STACJONARNE", "status": "ODWOŁANE",
                 "status_reason": "Zwolnienie lekarskie", "status_source": "PDF_TEXT_AND_RED_FRAME"},
                {"time": "17:30-18:15", "title": "Podstawy ekonomii", "lecturer": "dr Małgorzata Guziń",
                 "type": "ćwiczenia", "mode": "STACJONARNE", "status": "ODWOŁANE",
                 "status_reason": "Zwolnienie lekarskie", "status_source": "PDF_TEXT_AND_RED_FRAME"},
                {"time": "18:30-20:00", "title": "Wspólna polityka zagraniczna i bezpieczeństwo",
                 "lecturer": "dr Jolanta Martuszewska", "type": "ćwiczenia", "mode": "STACJONARNE", "room": "105"},
            ],
        }
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(".class-card.cancelled{", html)
        self.assertIn(".class-status{", html)

        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed in this environment")
        card = re.search(r"function classCard\(item,day\)\{.*?\n\s+\}", html, re.S)
        item_mode = re.search(r"function itemMode\(item,day\)\{.*?\}", html)
        is_cancelled = re.search(r"function isCancelledItem\(item\)\{.*?\}", html)
        for name, match in (("classCard", card), ("itemMode", item_mode), ("isCancelledItem", is_cancelled)):
            self.assertIsNotNone(match, f"Brak funkcji {name}")
        script = r"""
const day = __DAY__;
function esc(value){return String(value??'');}
""" .replace("__DAY__", json.dumps(source_day, ensure_ascii=False)) + "\n" + "\n".join(
            match.group(0) for match in (item_mode,is_cancelled,card)
        ) + r"""
const html = day.items.map(item => classCard(item,day)).join("");
console.log(JSON.stringify({
  html,
  cancelled: day.items.filter(isCancelledItem).length,
  active: day.items.filter(item => !isCancelledItem(item)).length
}));
"""
        result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
        output = json.loads(result.stdout)
        self.assertEqual(output["cancelled"], 4)
        self.assertEqual(output["active"], 1)
        self.assertEqual(output["html"].count("class-card cancelled"), 4)
        self.assertEqual(output["html"].count("Zwolnienie lekarskie"), 4)
        self.assertEqual(output["html"].count("ODWOŁANE"), 4)
        self.assertIn("Wspólna polityka zagraniczna", output["html"])

    def test_dashboard_summary_keeps_medical_leave_out_of_next_lesson(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        schedule = json.loads((ROOT / "schedule.json").read_text(encoding="utf-8"))
        source_day = schedule["days"]["2026-11-19"]
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed in this environment")
        summary = re.search(r"function dashboardSummary\\(day,selectedISO,now=new Date\\(\\)\\)\\{.*?\\n    \\}", html, re.S)
        time_helper = re.search(r"function dashboardTimeMinutes\\(value,part=0\\)\\{.*?\\}", html)
        cancelled_helper = re.search(r"function isCancelledItem\\(item\\)\\{.*?\\}", html)
        mode_helper = re.search(r"function itemMode\\(item,day\\)\\{.*?\\}", html)
        for name, match in (("dashboardSummary", summary), ("dashboardTimeMinutes", time_helper),
                            ("isCancelledItem", cancelled_helper), ("itemMode", mode_helper)):
            self.assertIsNotNone(match, f"Brak funkcji {name}")
        script = r"""
const day = __DAY__;
function localISODate(date) {
  return date.getFullYear()+'-'+String(date.getMonth()+1).padStart(2,'0')+'-'+String(date.getDate()).padStart(2,'0');
}
""" .replace("__DAY__", json.dumps(source_day, ensure_ascii=False)) + "\\n" + "\\n".join(
            match.group(0) for match in (time_helper,cancelled_helper,mode_helper,summary)
        ) + r"""
const result = dashboardSummary(day,"2026-11-19",new Date(2026,10,19,15,15));
console.log(JSON.stringify({
  activeCount:result.activeCount,
  remoteCount:result.remoteCount,
  cancelledCount:result.cancelledCount,
  nextTime:result.nextItem && result.nextItem.time,
  nextTitle:result.nextItem && result.nextItem.title,
  nextLabel:result.nextLabel
}));
"""
        result = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
        output = json.loads(result.stdout)
        self.assertEqual(output["activeCount"], 1)
        self.assertEqual(output["cancelledCount"], 4)
        self.assertEqual(output["nextTime"], "18:30-20:00")
        self.assertEqual(output["nextTitle"], "Wspólna polityka zagraniczna")
        self.assertEqual(output["nextLabel"], "NAJBLIŻSZE")

    def test_explicit_date_deep_links_override_automatic_date(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("hasExplicitDate?queryDate:localISODate()", html)
        self.assertIn("!state.hasExplicitDate&&!state.hasUserSelectedDate", html)

    def test_day_strip_is_horizontally_scrollable_and_covers_schedule_dates(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(".week-strip{display:flex", html)
        self.assertIn("overflow-x:auto", html)
        self.assertIn("touch-action:pan-x", html)
        self.assertIn("scroll-snap-type:x proximity", html)
        self.assertIn("const dates=Object.keys(state.days).sort()", html)
        self.assertIn("container.scrollLeft=Math.max(0,active.offsetLeft-(container.clientWidth-active.offsetWidth)/2)", html)

    def test_open_notification_restores_day_navigation(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("state.view='day';$('dayNavigation').hidden=false", html)

    def test_global_header_search_and_icon_only_day_actions(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="openGlobalSearch"', html)
        self.assertIn('id="copyDay"', html)
        self.assertIn('id="downloadDay"', html)
        self.assertIn('aria-label="Kopiuj plan wybranego dnia"', html)
        self.assertIn('aria-label="Pobierz plan wybranego dnia jako TXT"', html)
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

    def test_day_navigation_shows_weekday_chips_without_selected_datebar(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        navigation = html.split('<div class="day-navigation" id="dayNavigation">', 1)[1].split("</div>", 1)[0]
        self.assertIn('id="weekStrip"', navigation)
        self.assertNotIn('id="selectedDateLabel"', html)
        self.assertNotIn('id="selectedWeekdayLabel"', html)
        self.assertNotIn('id="selectedModeBadge"', html)
        self.assertNotIn('id="previousDay"', html)
        self.assertNotIn('id="nextDay"', html)
        self.assertNotIn("function renderDateHeader", html)

    def test_copy_download_icons_are_in_header_and_not_below_day_strip(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        header = html.split('<header class="topbar surface">', 1)[1].split("</header>", 1)[0]
        day_navigation = html.split('<div class="day-navigation" id="dayNavigation">', 1)[1].split('<main>', 1)[0]
        self.assertIn('id="copyDay"', header)
        self.assertIn('id="downloadDay"', header)
        self.assertNotIn('id="copyDay"', day_navigation)
        self.assertNotIn('id="downloadDay"', day_navigation)

    def test_brand_name_uses_regular_not_bold_weight(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('.brand-title{font-size:14px;font-weight:400', html)

    def test_day_view_shows_loading_skeleton_before_schedule_arrives(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("isLoading:true", html)
        self.assertIn("function renderLoadingDay(host)", html)
        self.assertIn('class="skeleton-card"', html)
        self.assertIn("state.isLoading=false", html)

    def test_empty_day_shows_the_next_available_lessons(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("function renderUpcomingLessons(host)", html)
        self.assertIn("Najbliższe zajęcia", html)
        self.assertIn("items.slice(0,3)", html)
        self.assertIn("Przejdź do planu tego dnia", html)
        self.assertIn("date>=anchor", html)

    def test_sync_bar_distinguishes_plan_change_from_browser_fetch(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("Plan ostatnio zmieniono:", html)
        self.assertIn("Dane pobrano:", html)
        self.assertIn("state.lastFetchedAt=new Date()", html)
        self.assertIn(r"/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/", html)
        self.assertNotIn("Ostatnia synchronizacja:", html)
        sync_css = html.split(".syncbar{", 1)[1].split("}", 1)[0]
        self.assertNotIn("margin-top:auto", sync_css)

    def test_premium_neon_orb_button_skin_is_present(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(".icon-button{", html)
        self.assertIn("border-radius:50%", html)
        self.assertIn("background:linear-gradient(145deg,rgba(48,67,105,.7),rgba(12,26,49,.88))", html)
        self.assertIn("backdrop-filter:blur(20px) saturate(135%)", html)
        self.assertIn(".dashboard-next:after", html)
        self.assertIn(".dashboard-stat.cancelled .dashboard-stat-value", html)
        self.assertIn("linear-gradient(145deg,rgba(77,31,56,.72),rgba(28,20,44,.88))", html)

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
        self.assertEqual(package_data["devDependencies"]["wrangler"], "4.168.0")
        self.assertEqual(package_data["engines"]["node"], ">=26.13.1")
        self.assertEqual(package_data["packageManager"], "npm@12.2.3")
        self.assertNotIn("web-push", package_data.get("devDependencies", {}))

    def test_service_worker_fetches_push_config_from_network_first(self):
        service_worker = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertIn('pans-plan-shell-v12', service_worker)
        self.assertIn('const isNavigation = request.mode === "navigate" || url.pathname.endsWith("/index.html")', service_worker)
        self.assertIn('const liveRequest = new Request(request, { cache: "no-store" })', service_worker)
        self.assertIn('const isPushConfig = url.pathname.endsWith("/push-config.js")', service_worker)
        self.assertIn('new Request(request, { cache: "no-store" })', service_worker)
        self.assertIn('const response = await fetch(liveRequest)', service_worker)
        self.assertIn('const stableRequest = new Request(url.origin + url.pathname', service_worker)
        self.assertIn('await cache.put(stableRequest, response.clone())', service_worker)
        self.assertIn('caches.match(stableRequest)', service_worker)


    def test_full_pdf_audit_is_mandatory_before_schedule_publication(self):
        workflow = (ROOT / ".github" / "workflows" / "update_schedule.yml").read_text(encoding="utf-8")
        audit_pos = workflow.find("run: python audit_plan.py")
        publish_pos = workflow.find("name: Zapisz plan, historię i oczekujące powiadomienia")
        self.assertGreaterEqual(audit_pos, 0)
        self.assertGreater(publish_pos, audit_pos)
        audit_section = workflow[workflow.rfind("- name:", 0, audit_pos):audit_pos]
        self.assertNotIn("if:", audit_section)

    def test_push_backend_setup_is_documented(self):
        setup = (ROOT / "cloudflare" / "README.md").read_text(encoding="utf-8")
        for value in ("PUSH_WORKER_URL", "PUSH_DISPATCH_TOKEN", "VAPID_PRIVATE_KEY", "PUSH_KV",
                      "Root directory", "npm install --no-audit --no-fund",
                      "npm run deploy", "Enable Preview Builds"):
            self.assertIn(value, setup)


if __name__ == "__main__":
    unittest.main()
