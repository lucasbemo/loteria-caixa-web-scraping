from __future__ import annotations

from typing import Iterable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from ..errors import AutomationError


def _first_non_empty(values: Iterable[str]) -> list[str]:
    return [value for value in values if value and value.strip()]


def visible_locator_by_selectors(page: Page, selectors: Iterable[str], timeout_ms: int = 2000) -> Locator:
    for selector in _first_non_empty(selectors):
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except PlaywrightTimeoutError:
            continue
    raise AutomationError(f"No visible element found for selectors: {list(_first_non_empty(selectors))}")


def find_visible_locator_by_selectors(page: Page, selectors: Iterable[str], timeout_ms: int = 1200) -> Locator | None:
    for selector in _first_non_empty(selectors):
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except PlaywrightTimeoutError:
            continue
    return None


def click_by_text(page: Page, text: str, exact: bool = False, timeout_ms: int = 5000) -> None:
    locator = page.get_by_text(text, exact=exact).first
    locator.wait_for(state="visible", timeout=timeout_ms)
    locator.click()


def click_if_present_by_text(page: Page, text: str, exact: bool = False, timeout_ms: int = 1200) -> bool:
    if not text or not text.strip():
        return False
    locator = page.get_by_text(text, exact=exact).first
    try:
        locator.wait_for(state="visible", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        return False
    try:
        locator.click(timeout=timeout_ms)
    except PlaywrightTimeoutError:
        return False
    return True


def click_if_present_by_selectors(page: Page, selectors: Iterable[str], timeout_ms: int = 1200) -> bool:
    locator = find_visible_locator_by_selectors(page, selectors, timeout_ms=timeout_ms)
    if locator is None:
        return False
    try:
        locator.click(timeout=timeout_ms)
    except PlaywrightTimeoutError:
        return False
    return True


def any_visible_by_selectors(page: Page, selectors: Iterable[str], timeout_ms: int = 1200) -> bool:
    return find_visible_locator_by_selectors(page, selectors, timeout_ms=timeout_ms) is not None


def click_first_available(page: Page, selectors: Iterable[str], fallback_text: str | None = None, exact_text: bool = False) -> None:
    selectors = _first_non_empty(selectors)
    if selectors:
        visible_locator_by_selectors(page, selectors).click()
        return
    if fallback_text:
        click_by_text(page, fallback_text, exact=exact_text)
        return
    raise AutomationError("No selector or fallback text provided for click action")


def fill_first_available(page: Page, value: str, selectors: Iterable[str], timeout_ms: int = 2000) -> None:
    locator = visible_locator_by_selectors(page, selectors, timeout_ms=timeout_ms)
    locator.fill(value)


def text_exists(page: Page, text: str, exact: bool = False, timeout_ms: int = 5000) -> bool:
    try:
        page.get_by_text(text, exact=exact).first.wait_for(state="visible", timeout=timeout_ms)
        return True
    except (PlaywrightTimeoutError, PlaywrightError):
        return False


def normalize_money(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit() or ch == ",")
