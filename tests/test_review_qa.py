import sys
import types

from creation.review.qa import _playwright_review


def test_browser_review_reload_allows_persistent_network_activity(monkeypatch):
    calls = []

    class Response:
        status = 200

    class ConsoleMessage:
        type = "warning"
        text = "stream remains connected"

    class Page:
        def __init__(self):
            self.console_handler = None

        def on(self, event, handler):
            calls.append(("on", event))
            self.console_handler = handler

        def goto(self, url, **kwargs):
            calls.append(("goto", url, kwargs))
            return Response()

        def title(self):
            return "Creation"

        def reload(self, **kwargs):
            calls.append(("reload", kwargs))
            if kwargs["wait_until"] == "networkidle":
                raise TimeoutError("persistent stream")
            self.console_handler(ConsoleMessage())

    class Browser:
        def __init__(self):
            self.page = Page()

        def new_page(self, **kwargs):
            calls.append(("new_page", kwargs))
            return self.page

        def close(self):
            calls.append(("close",))

    class Chromium:
        def __init__(self, browser):
            self.browser = browser

        def launch(self, **kwargs):
            calls.append(("launch", kwargs))
            return self.browser

    browser = Browser()
    playwright = types.SimpleNamespace(chromium=Chromium(browser))

    class PlaywrightContext:
        def __enter__(self):
            return playwright

        def __exit__(self, exc_type, exc, tb):
            return False

    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = PlaywrightContext
    package = types.ModuleType("playwright")
    package.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)

    report = _playwright_review(["http://127.0.0.1:8787/dashboard"])

    assert report is not None
    assert not [finding for finding in report.findings if finding.severity == "error"]
    assert report.findings[0].note == "Console warning: stream remains connected"
    assert ("reload", {"wait_until": "domcontentloaded", "timeout": 12000}) in calls
    assert calls.index(("on", "console")) < next(
        i for i, call in enumerate(calls) if call[0] == "goto"
    )
