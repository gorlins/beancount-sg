"""Regenerate the Fava extension screenshots in ``images/`` from the example ledgers.

Run ``make screenshots`` from the repository root to regenerate them all, or
``make screenshots NAMES=year-in-review`` for only the named ones, so that
changing one extension doesn't touch the others' screenshots. (If Playwright has
no browser yet, first run ``uv run --with playwright playwright install
chromium``.)

It serves the example ledgers in ``ledgers/`` with Fava on a free port, opens
each extension's page in headless Chromium and saves the page's content area as
a PNG. It only looks at pages: Batch Edit's search is previewed, never applied.
``example.beancount`` holds the data for most screenshots; an extension whose
data would change the others' (e.g. years of history) has a ledger of its own.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

HERE = Path(__file__).parent
# The example ledgers, by the URL slug Fava gives them (from their titles).
LEDGERS = {
    "example": HERE / "ledgers" / "example.beancount",
    "household": HERE / "ledgers" / "household.beancount",
}
IMAGES = HERE / "images"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            urllib.request.urlopen(url)
            return
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.25)


# The bounds of an element's content, in page coordinates, so a screenshot covers
# all of it without the empty space below: Fava's content area fills the window
# and scrolls, so it can be taller or shorter than what's in it. The margin adds
# space to the right and below.
CONTENT_BOUNDS = """([selector, margin]) => {
  const element = document.querySelector(selector);
  const box = element.getBoundingClientRect();
  const children = [...element.children].map((child) => child.getBoundingClientRect());
  const bottom = Math.max(...children.map((child) => child.bottom)) + element.scrollTop;
  const right = Math.max(box.right, ...children.map((child) => child.right));
  const width = right - box.left + margin;
  return {x: box.left, y: box.top, width, height: bottom - box.top + margin};
}"""


def save(page: Page, name: str, selector: str = "article", margin: int = 24) -> None:
    """Save the element's content as ``images/<name>.png``."""
    bounds = page.evaluate(CONTENT_BOUNDS, [selector, margin])
    viewport = page.viewport_size
    page.set_viewport_size(
        {
            "width": max(viewport["width"], int(bounds["x"] + bounds["width"])),
            "height": max(viewport["height"], int(bounds["y"] + bounds["height"])),
        }
    )
    page.screenshot(path=IMAGES / f"{name}.png", clip=bounds, animations="disabled")
    page.set_viewport_size(viewport)
    print(f"wrote {IMAGES / name}.png")


def report_url(root: str, ledger: str, report: str) -> str:
    """The URL of an extension's report, e.g. ``Checkbook/``, in one of the ledgers."""
    return f"{root}/{ledger}/extension/{report}"


def checkbook(page: Page, root: str) -> None:
    page.goto(report_url(root, "example", "Checkbook/"), wait_until="networkidle")
    save(page, "checkbook")


def batch_edit(page: Page, root: str) -> None:
    search = "payee_regex=sq%20%5C*corner&new_payee=%7Bplaid_payee%7D"
    page.goto(report_url(root, "example", f"BatchEdit/?{search}"), wait_until="networkidle")
    page.locator("#batch-edit-apply").wait_for()
    save(page, "batch-edit")


def rewards(page: Page, root: str) -> None:
    page.goto(report_url(root, "example", "CreditCardRewards/"), wait_until="networkidle")
    page.get_by_text("Icicle", exact=True).click()
    save(page, "rewards")


def update_status(page: Page, root: str) -> None:
    page.goto(report_url(root, "example", "UpdateStatus/"), wait_until="networkidle")
    save(page, "update-status")


def travel(page: Page, root: str) -> None:
    page.goto(report_url(root, "example", "Travel/"), wait_until="networkidle")
    page.get_by_text("Icicle", exact=True).click()
    save(page, "travel")
    page.click('a[href*="chart=Over"]')
    page.wait_for_load_state("networkidle")
    save(page, "travel-over-time", "svelte-component", margin=0)


def payees(page: Page, root: str) -> None:
    page.goto(report_url(root, "example", "PayeeReview/"), wait_until="networkidle")
    save(page, "payees")


def year_in_review(page: Page, root: str) -> None:
    page.goto(report_url(root, "household", "YearInReview/?time=2024"), wait_until="networkidle")
    save(page, "year-in-review")


def cash_flow(page: Page, root: str) -> None:
    page.goto(report_url(root, "household", "CashFlow/?time=2024"), wait_until="networkidle")
    save(page, "cash-flow")


# Each screenshot's name, and the function that saves it (``travel`` saves two).
SCREENSHOTS = {
    "checkbook": checkbook,
    "batch-edit": batch_edit,
    "rewards": rewards,
    "update-status": update_status,
    "travel": travel,
    "payees": payees,
    "year-in-review": year_in_review,
    "cash-flow": cash_flow,
}


def main(names: list[str]) -> None:
    unknown = set(names) - set(SCREENSHOTS)
    if unknown:
        sys.exit(f"Unknown screenshots: {sorted(unknown)}; choose from {sorted(SCREENSHOTS)}")
    port = free_port()
    root = f"http://127.0.0.1:{port}"
    fava = subprocess.Popen(
        ["fava", *map(str, LEDGERS.values()), "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for(f"{root}/example/")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1300, "height": 800}, device_scale_factor=2)
            for name in names or SCREENSHOTS:
                SCREENSHOTS[name](page, root)
            browser.close()
    finally:
        fava.terminate()
        fava.wait()


if __name__ == "__main__":
    main(sys.argv[1:])
