from __future__ import annotations

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from .config import AppConfig


def start_browser(config: AppConfig) -> tuple[Playwright, BrowserContext, Page]:
    playwright = sync_playwright().start()
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(config.user_data_dir),
        headless=config.headless,
        slow_mo=config.slow_mo_ms,
    )
    context.set_default_timeout(config.timeout_ms)
    page = context.pages[0] if context.pages else context.new_page()
    return playwright, context, page


def close_browser(playwright: Playwright, context: BrowserContext) -> None:
    context.close()
    playwright.stop()
