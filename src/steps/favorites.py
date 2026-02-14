from __future__ import annotations

import logging
import re
import time
import unicodedata
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ..config import AppConfig
from ..errors import AutomationError
from ..utils.snapshots import save_snapshot
from ..utils.ui import visible_locator_by_selectors


def _try_click(locator, timeout_ms: int = 1800) -> bool:
    try:
        locator.wait_for(state="visible", timeout=timeout_ms)
        locator.click(timeout=timeout_ms)
        return True
    except (PlaywrightTimeoutError, PlaywrightError):
        return False


def _open_menu_if_needed(page: Page, logger: logging.Logger) -> bool:
    menu_selectors = [
        "button[aria-label*='menu' i]",
        ".navbar-toggle",
        "button:has-text('Menu')",
        "a:has-text('Menu')",
        "[data-testid='menu-button']",
    ]
    for selector in menu_selectors:
        if _try_click(page.locator(selector).first):
            logger.info("Opened navigation menu using selector: %s", selector)
            page.wait_for_timeout(400)
            return True

    if _try_click(page.get_by_role("button", name=re.compile(r"menu|navega", re.IGNORECASE)).first):
        logger.info("Opened navigation menu by role")
        page.wait_for_timeout(400)
        return True

    return False


def _favorite_entry_candidates(page: Page, config: AppConfig) -> list:
    favorite_regex = re.compile(r"carrinh(?:o|os)\s+favorit", re.IGNORECASE)
    candidates = [
        page.get_by_role("link", name=favorite_regex).first,
        page.get_by_role("button", name=favorite_regex).first,
        page.get_by_role("menuitem", name=favorite_regex).first,
        page.locator("a,button").filter(has_text=favorite_regex).first,
    ]

    if config.favorites_entry_text:
        text_regex = re.compile(re.escape(config.favorites_entry_text), re.IGNORECASE)
        candidates.extend(
            [
                page.get_by_role("link", name=text_regex).first,
                page.get_by_role("button", name=text_regex).first,
                page.get_by_role("menuitem", name=text_regex).first,
            ]
        )

    return candidates


def _try_open_favorites_direct(page: Page, config: AppConfig, logger: logging.Logger) -> bool:
    if config.favorites_entry_selector and config.favorites_entry_selector.strip():
        if _try_click(page.locator(config.favorites_entry_selector).first, timeout_ms=2000):
            logger.info("Opened favorites section using FAVORITES_ENTRY_SELECTOR")
            return True

    for candidate in _favorite_entry_candidates(page, config):
        if _try_click(candidate, timeout_ms=2000):
            logger.info("Opened favorites section by text/regex")
            return True

    return False


def _open_account_menu(page: Page, config: AppConfig, logger: logging.Logger) -> bool:
    if config.account_menu_selector and config.account_menu_selector.strip():
        if _try_click(page.locator(config.account_menu_selector).first, timeout_ms=2200):
            logger.info("Opened account menu using ACCOUNT_MENU_SELECTOR")
            return True

    account_text = (config.account_menu_text or "Minha Conta").strip() or "Minha Conta"
    account_regex = re.compile(re.escape(account_text), re.IGNORECASE)
    for candidate in [
        page.get_by_role("button", name=account_regex).first,
        page.get_by_role("link", name=account_regex).first,
        page.get_by_text(account_regex).first,
    ]:
        if _try_click(candidate, timeout_ms=2200):
            logger.info("Opened account menu by text: %s", account_text)
            return True

    if _open_menu_if_needed(page, logger):
        return True

    return False


def _open_favorites_section(page: Page, config: AppConfig, logger: logging.Logger, run_dir: Path) -> bool:
    if _try_open_favorites_direct(page, config, logger):
        return True

    if _open_account_menu(page, config, logger):
        save_snapshot(page, run_dir, "account_menu_opened")
        page.wait_for_timeout(500)
        if _try_open_favorites_direct(page, config, logger):
            logger.info("Opened favorites section after opening account/menu")
            return True

    return False


def _wait_for_favorites_list(page: Page, timeout_ms: int = 20000) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000)
    spinner_selectors = [
        ".fa-spinner",
        ".spinner",
        "img[src*='loading' i]",
        "[class*='loading' i]",
    ]

    while time.monotonic() < deadline:
        rows = page.locator("table tbody tr")
        if rows.count() > 0:
            return True

        if page.locator("table").count() > 0:
            for selector in spinner_selectors:
                try:
                    if page.locator(selector).first.is_visible(timeout=300):
                        page.wait_for_timeout(300)
                        break
                except PlaywrightError:
                    continue
            else:
                page.wait_for_timeout(250)
        else:
            page.wait_for_timeout(250)

    return False


def _normalize_text(value: str) -> str:
    lowered = value.strip().lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(without_marks.split())


def _find_favorite_row(page: Page, favorite_name: str):
    target = _normalize_text(favorite_name)
    rows = page.locator("table tbody tr")
    count = rows.count()
    for idx in range(count):
        row = rows.nth(idx)
        try:
            text = row.inner_text(timeout=1200)
        except PlaywrightTimeoutError:
            continue
        if target in _normalize_text(text):
            return row
    return None


def _visible_favorite_names(page: Page) -> list[str]:
    names = page.locator("table tbody tr td:first-child")
    result: list[str] = []
    for idx in range(names.count()):
        try:
            name = names.nth(idx).inner_text(timeout=800).strip()
        except PlaywrightTimeoutError:
            continue
        if name:
            result.append(name)
    return result


def _click_add_to_cart_in_row(row, logger: logging.Logger) -> bool:
    action_candidates = [
        row.locator("a[title*='adicionar' i],button[title*='adicionar' i]").first,
        row.locator("a[aria-label*='adicionar' i],button[aria-label*='adicionar' i]").first,
        row.locator("a:has(i.fa-shopping-cart),button:has(i.fa-shopping-cart)").first,
        row.locator("a:has(.fa-shopping-cart),button:has(.fa-shopping-cart)").first,
        row.locator("td:last-child a, td:last-child button").nth(1),
        row.locator("td:last-child a, td:last-child button").first,
    ]

    for candidate in action_candidates:
        if _try_click(candidate, timeout_ms=2000):
            logger.info("Clicked add-to-cart action in favorite row")
            return True

    return False


def run_favorites_flow(page: Page, config: AppConfig, logger: logging.Logger, run_dir: Path) -> None:
    logger.info("Opening favorites/cart section")
    if not _open_favorites_section(page, config, logger, run_dir):
        raise AutomationError("Could not open favorite cart section")

    save_snapshot(page, run_dir, "favorites_opened")

    logger.info("Waiting favorites list to load")
    if not _wait_for_favorites_list(page, timeout_ms=20000):
        raise AutomationError("Favorites list did not load in time")

    logger.info("Finding favorite item row and clicking add-to-cart action")
    row = _find_favorite_row(page, config.favorite_item_name_exact)
    if row is None:
        names = _visible_favorite_names(page)
        raise AutomationError(
            f"Favorite item '{config.favorite_item_name_exact}' was not found. Visible favorites: {names}"
        )

    if config.favorites_add_button_selector and config.favorites_add_button_selector.strip():
        if not _try_click(row.locator(config.favorites_add_button_selector).first, timeout_ms=2000):
            raise AutomationError("Favorite row found, but add button selector did not match a clickable element")
    elif not _click_add_to_cart_in_row(row, logger):
        raise AutomationError("Favorite row found, but no clickable add-to-cart action was detected")

    save_snapshot(page, run_dir, "favorite_item_added")

    cart_badges = [
        "[data-testid='cart-count']",
        ".cart-count",
        "span.badge",
    ]
    try:
        visible_locator_by_selectors(page, cart_badges, timeout_ms=2000)
    except Exception:
        logger.info("Cart badge not detected; continuing with checkout step")
