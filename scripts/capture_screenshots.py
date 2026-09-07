"""Capture the README screenshots into docs/screenshots/.

Real-browser (Chromium via Playwright) captures at 2x, desktop width, so the
app renders its sidebar rather than the mobile bottom nav.

Prerequisites:
  1. Install Playwright once:
       pip install playwright
       python -m playwright install chromium
  2. Load demo data so the screenshots look alive (back up your real DB first —
     seed_demo.py wipes operational rows):
       PYTHONPATH=. python scripts/seed_demo.py
  3. Have the app serving on http://localhost:8000  (python run.py)

Then, from the project root:
    python scripts/capture_screenshots.py

Restore your real database afterwards if you seeded demo data.
"""
import os
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("BALANCE_URL", "http://localhost:8000")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "screenshots")
WIDTH = 1360

# (filename, path, viewport_height, scroll_to_text_or_None)
SHOTS = [
    ("dashboard.png",    "/",             1040, None),
    ("money-health.png", "/",             1180, "This month"),
    ("transactions.png", "/transactions", 1040, None),
    ("food-log.png",     "/food-log",     1040, None),
    ("forecast.png",     "/forecast",     1120, None),
    ("pantry.png",       "/pantry",       1000, None),
]

SCROLL_JS = """(t) => {
  const el = [...document.querySelectorAll('*')]
    .find(e => e.children.length === 0 && e.textContent.trim() === t);
  if (el) { el.scrollIntoView({block: 'start'}); window.scrollBy(0, -16); }
  return !!el;
}"""


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": WIDTH, "height": 1040}, device_scale_factor=2)
        page = ctx.new_page()
        for name, path, height, scroll_text in SHOTS:
            page.set_viewport_size({"width": WIDTH, "height": height})
            page.goto(BASE + path, wait_until="load")
            time.sleep(2.5)  # let NiceGUI hydrate + ECharts/ring gauges render
            if scroll_text:
                page.evaluate(SCROLL_JS, scroll_text)
                time.sleep(1.0)
            page.screenshot(path=os.path.join(OUT, name))
            print(f"saved {name}")
        browser.close()
    print("done")


if __name__ == "__main__":
    main()
