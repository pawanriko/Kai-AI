"""Playwright browser runner (Phase 8).

Each action is SELF-CONTAINED: it carries its own URL, opens a
fresh headless browser, acts, and closes it. Individually
approved actions cannot share a live page (there is no persistent
browser session on a free Render instance), so navigate-then-click
flows are expressed as one action per step, each with its URL.

Playwright is deliberately NOT a hard dependency: it needs
browser binaries as well as the pip package, and neither is
installed on the server today. The import happens lazily inside
the default factory — when Playwright is missing, the action
fails with a clear message instead of crashing the import of
this module. Live browser actions need `pip install playwright`
plus `playwright install chromium` on the host; that setup is
deferred, and no live browser run has happened yet.

Safety: URLs pass the same public-URL guard as fetch_page — the
browser must not be steered at localhost or cloud metadata
addresses.
"""

from . import research

_MAX_TEXT_CHARS = 2000


def _default_playwright_factory():
    """The real Playwright entry point. Raises ImportError when
    Playwright is not installed — the caller turns that into a
    failed action with a clear message."""
    from playwright.sync_api import sync_playwright

    return sync_playwright()


class BrowserRunner:
    """Runs one self-contained browser action. `playwright_factory`
    is injectable so tests can drive a fake browser without the
    real dependency installed."""

    def __init__(self, playwright_factory=None):
        self._factory = playwright_factory or _default_playwright_factory

    def run(self, action, payload):
        url = (payload or {}).get("url") or ""
        research._check_url_public(url)
        with self._factory() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, timeout=30000)
                if action == "navigate":
                    return f"Opened {url} — title: {page.title()}"
                if action == "click":
                    selector = payload["selector"]
                    page.click(selector, timeout=10000)
                    return (
                        f"Clicked {selector} on {url} "
                        f"— title now: {page.title()}"
                    )
                if action == "type":
                    selector = payload["selector"]
                    page.fill(selector, payload["text"], timeout=10000)
                    return f"Typed into {selector} on {url}"
                if action == "extract":
                    selector = payload.get("selector")
                    if selector:
                        text = page.locator(selector).inner_text(timeout=10000)
                    else:
                        text = page.locator("body").inner_text(timeout=10000)
                    return text[:_MAX_TEXT_CHARS]
                raise ValueError(f"unknown browser action: {action}")
            finally:
                browser.close()
