from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ..config import AppConfig
from ..errors import AutomationError
from ..utils.snapshots import save_snapshot
from ..utils.ui import (
    any_visible_by_selectors,
    click_if_present_by_selectors,
    click_if_present_by_text,
    find_visible_locator_by_selectors,
    fill_first_available,
    text_exists,
)


def _username_selectors(config: AppConfig) -> list[str]:
    return [
        config.login_username_selector,
        "input[name='username']",
        "input[autocomplete='username']",
        "input[name='cpf']",
        "input[name*='cpf']",
        "input[id*='cpf']",
        "input[placeholder*='CPF']",
        "input[placeholder*='cpf']",
        "input[aria-label*='CPF']",
        "input[aria-label*='cpf']",
        "input[type='text']",
        "input[type='email']",
    ]


def _password_selectors(config: AppConfig) -> list[str]:
    return [
        config.login_password_selector,
        "input[name='password']",
        "input[autocomplete='current-password']",
        "input[name='senha']",
        "input[name*='senha']",
        "input[id*='senha']",
        "input[placeholder*='Senha']",
        "input[placeholder*='senha']",
        "input[aria-label*='Senha']",
        "input[aria-label*='senha']",
        "input[type='password']",
    ]


def _login_otp_selectors(config: AppConfig) -> list[str]:
    return [
        config.login_otp_input_selector,
        "input[name='otp']",
        "input[name='codigo']",
        "input[name*='codigo']",
        "input[id*='codigo']",
        "input[placeholder*='Código']",
        "input[placeholder*='codigo']",
        "input[placeholder*='código']",
        "input[aria-label*='Código']",
        "input[aria-label*='codigo']",
        "input[aria-label*='código']",
        "input[inputmode='numeric']",
        "input[type='tel']",
        "input[type='text']",
    ]


def _login_inputs_visible(page: Page, config: AppConfig) -> bool:
    try:
        return any_visible_by_selectors(page, _username_selectors(config), timeout_ms=1200)
    except PlaywrightError:
        return False


def _password_visible(page: Page, config: AppConfig) -> bool:
    try:
        return any_visible_by_selectors(page, _password_selectors(config), timeout_ms=1200)
    except PlaywrightError:
        return False


def _login_otp_visible(page: Page, config: AppConfig) -> bool:
    try:
        return any_visible_by_selectors(page, _login_otp_selectors(config), timeout_ms=1200)
    except PlaywrightError:
        return False


def _clear_interstitials(page: Page, config: AppConfig, logger: logging.Logger) -> None:
    for _ in range(3):
        changed = False

        if click_if_present_by_selectors(page, [config.cookie_accept_selector], timeout_ms=1200):
            logger.info("Cookie banner accepted by selector")
            changed = True
        elif click_if_present_by_text(page, config.cookie_accept_text, exact=False, timeout_ms=1200):
            logger.info("Cookie banner accepted by text")
            changed = True

        if text_exists(page, config.age_gate_prompt_text, exact=False, timeout_ms=1000):
            if click_if_present_by_selectors(page, [config.age_gate_confirm_selector], timeout_ms=1200):
                logger.info("Age gate confirmed by selector")
                changed = True
            elif click_if_present_by_text(page, config.age_gate_confirm_text, exact=False, timeout_ms=1200):
                logger.info("Age gate confirmed by text")
                changed = True

        if click_if_present_by_selectors(page, [config.enter_site_selector], timeout_ms=1200):
            logger.info("Clicked site entry by selector")
            changed = True
        elif click_if_present_by_text(page, config.enter_site_text, exact=False, timeout_ms=1200):
            logger.info("Clicked site entry by text")
            changed = True

        if changed:
            page.wait_for_timeout(600)


def _is_logged_in_session(page: Page, config: AppConfig) -> bool:
    if _login_inputs_visible(page, config) or _password_visible(page, config) or _login_otp_visible(page, config):
        return False

    try:
        current_url = page.url or ""
    except PlaywrightError:
        current_url = ""
    if "login.caixa.gov.br" in current_url:
        return False

    logged_markers = [
        "a:has-text('Minha Conta')",
        "button:has-text('Minha Conta')",
        "[title*='Minha Conta' i]",
    ]
    has_logged_marker = any_visible_by_selectors(page, logged_markers, timeout_ms=1200)
    has_logged_text = text_exists(page, "Minha Conta", exact=False, timeout_ms=1200) or text_exists(
        page, "Olá", exact=False, timeout_ms=1200
    )
    has_login_cta = text_exists(page, config.access_login_text or "Acessar", exact=False, timeout_ms=800)

    return (has_logged_marker or has_logged_text) and not has_login_cta


def _resolve_active_page(page: Page, logger: logging.Logger) -> Page:
    pages = [candidate for candidate in page.context.pages if not candidate.is_closed()]
    if not pages:
        raise AutomationError("Browser has no active pages after login transition")

    if page.is_closed():
        next_page = pages[-1]
        logger.info("Switched to active page after previous page closed: %s", next_page.url)
        return next_page

    try:
        current_url = page.url or ""
    except PlaywrightError:
        current_url = ""

    if current_url and "login.caixa.gov.br" not in current_url:
        return page

    for candidate in reversed(pages):
        if candidate is page:
            continue
        try:
            candidate_url = candidate.url or ""
        except PlaywrightError:
            continue
        if candidate_url and "login.caixa.gov.br" not in candidate_url:
            logger.info("Switched to non-login page after transition: %s", candidate_url)
            return candidate

    for candidate in reversed(pages):
        if candidate is page:
            continue
        try:
            if "login.caixa.gov.br" in candidate.url:
                logger.info("Switched to login target page: %s", candidate.url)
                return candidate
        except PlaywrightError:
            continue

    return page


def _try_click_locator(locator, timeout_ms: int = 2000) -> bool:
    try:
        locator.wait_for(state="visible", timeout=timeout_ms)
        locator.click(timeout=timeout_ms)
        return True
    except (PlaywrightTimeoutError, PlaywrightError):
        return False


def _click_login_next_button(page: Page, config: AppConfig, logger: logging.Logger) -> bool:
    if config.login_next_selector and config.login_next_selector.strip():
        if _try_click_locator(page.locator(config.login_next_selector).first, timeout_ms=2500):
            logger.info("Clicked login next by selector")
            return True

    texts = [config.login_next_text, "Próximo"]
    checked: set[str] = set()
    for text in texts:
        key = (text or "").strip()
        if not key or key in checked:
            continue
        checked.add(key)

        if _try_click_locator(page.get_by_role("button", name=key, exact=True).first, timeout_ms=2500):
            logger.info("Clicked login next by role exact text: %s", key)
            return True
        if _try_click_locator(page.get_by_role("button", name=key, exact=False).first, timeout_ms=2000):
            logger.info("Clicked login next by role text: %s", key)
            return True
        if _try_click_locator(page.locator(f"button:has-text('{key}')").first, timeout_ms=2000):
            logger.info("Clicked login next by button text: %s", key)
            return True
        if _try_click_locator(page.locator(f"input[type='submit'][value*='{key}']").first, timeout_ms=2000):
            logger.info("Clicked login next by submit value: %s", key)
            return True

    return False


def _click_login_submit_button(page: Page, config: AppConfig, logger: logging.Logger) -> bool:
    if config.login_submit_selector and config.login_submit_selector.strip():
        if _try_click_locator(page.locator(config.login_submit_selector).first, timeout_ms=2500):
            logger.info("Clicked login submit by selector")
            return True

    if _try_click_locator(
        page.get_by_role("button", name=re.compile(r"entrar|acessar|continuar", re.IGNORECASE)).first,
        timeout_ms=2500,
    ):
        logger.info("Clicked login submit by button role regex")
        return True

    if _try_click_locator(page.locator("button:has-text('Entrar')").first, timeout_ms=2000):
        logger.info("Clicked login submit by button text")
        return True

    if _try_click_locator(page.locator("input[type='submit'][value*='Entrar']").first, timeout_ms=2000):
        logger.info("Clicked login submit by submit input")
        return True

    return False


def _click_login_otp_submit_button(page: Page, config: AppConfig, logger: logging.Logger) -> bool:
    if config.login_otp_submit_selector and config.login_otp_submit_selector.strip():
        if _try_click_locator(page.locator(config.login_otp_submit_selector).first, timeout_ms=2500):
            logger.info("Clicked login OTP submit by selector")
            return True

    if _try_click_locator(
        page.get_by_role("button", name=re.compile(r"enviar|confirmar|validar", re.IGNORECASE)).first,
        timeout_ms=2500,
    ):
        logger.info("Clicked login OTP submit by button role regex")
        return True

    if _try_click_locator(page.locator("button:has-text('Enviar')").first, timeout_ms=2000):
        logger.info("Clicked login OTP submit by Enviar text")
        return True

    if _try_click_locator(page.locator("button:has-text('Confirmar')").first, timeout_ms=2000):
        logger.info("Clicked login OTP submit by Confirmar text")
        return True

    return False


def _submit_login_otp(page: Page, config: AppConfig, logger: logging.Logger) -> Page:
    page.wait_for_timeout(400)
    page = _resolve_active_page(page, logger)

    if _password_visible(page, config):
        logger.info("OTP entry auto-advanced to password step")
        return page

    if not _login_otp_visible(page, config):
        current_url = ""
        try:
            current_url = page.url or ""
        except PlaywrightError:
            pass
        if "login.caixa.gov.br" not in current_url:
            logger.info("OTP entry auto-completed login flow")
            return page

    if _click_login_otp_submit_button(page, config, logger):
        return page

    otp_locator = find_visible_locator_by_selectors(page, _login_otp_selectors(config), timeout_ms=1500)
    if otp_locator is not None:
        try:
            otp_locator.press("Enter", timeout=1500)
            logger.info("Submitted login OTP by pressing Enter")
            return page
        except (PlaywrightTimeoutError, PlaywrightError):
            pass

    raise AutomationError(f"Unable to click login OTP submit button. current_url={page.url}")


def _wait_for_login_step(page: Page, config: AppConfig, logger: logging.Logger, timeout_ms: int = 30000) -> tuple[Page, str]:
    deadline = time.monotonic() + (timeout_ms / 1000)
    clicked_receive_code = False
    while time.monotonic() < deadline:
        page = _resolve_active_page(page, logger)
        if _password_visible(page, config):
            logger.info("Password field detected")
            return page, "password"

        if _login_otp_visible(page, config):
            logger.info("Login validation code field detected")
            return page, "otp"

        if not clicked_receive_code and _try_click_locator(
            page.get_by_role("button", name=re.compile(r"receber\s+c[oó]digo", re.IGNORECASE)).first,
            timeout_ms=1500,
        ):
            clicked_receive_code = True
            logger.info("Clicked login validation button by regex: Receber codigo")
            page.wait_for_timeout(500)
            continue

        page.wait_for_timeout(250)

    raise AutomationError(f"Login did not advance to password or validation code step after clicking next. current_url={page.url}")


def _wait_for_password_or_login_completion(
    page: Page, config: AppConfig, logger: logging.Logger, timeout_ms: int = 30000
) -> tuple[Page, str]:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        page = _resolve_active_page(page, logger)
        if _password_visible(page, config):
            logger.info("Password field detected after OTP submission")
            return page, "password"

        current_url = ""
        try:
            current_url = page.url or ""
        except PlaywrightError:
            pass
        if "login.caixa.gov.br" not in current_url:
            logger.info("Login flow appears complete after OTP, current URL: %s", current_url)
            return page, "done"

        page.wait_for_timeout(250)

    raise AutomationError(f"Login did not complete after OTP submission. current_url={page.url}")


def _is_login_domain(page: Page) -> bool:
    try:
        return "login.caixa.gov.br" in (page.url or "")
    except PlaywrightError:
        return False


def _prepare_login_page(page: Page, config: AppConfig, logger: logging.Logger, run_dir: Path) -> None:
    logger.info("Preparing page for login form")

    for _ in range(4):
        if _login_inputs_visible(page, config):
            logger.info("Login form detected")
            return

        if _is_logged_in_session(page, config):
            logger.info("Session already active while preparing login page")
            return

        _clear_interstitials(page, config, logger)

        changed = False

        if click_if_present_by_selectors(page, [config.access_login_selector], timeout_ms=1200):
            logger.info("Clicked login access by selector")
            changed = True
        elif click_if_present_by_text(page, config.access_login_text, exact=False, timeout_ms=1200):
            logger.info("Clicked login access by text")
            changed = True

        if _login_inputs_visible(page, config):
            logger.info("Login form detected")
            return

        if _is_logged_in_session(page, config):
            logger.info("Session became active during login page preparation")
            return

        if changed:
            page.wait_for_timeout(600)

    shot = save_snapshot(page, run_dir, "login_form_not_visible")
    raise AutomationError(
        f"Login form was not visible after handling interstitials. url={page.url} title={page.title()} screenshot={shot}"
    )


def run_login(page: Page, config: AppConfig, logger: logging.Logger, run_dir: Path) -> Page:
    logger.info("Opening base URL")
    page.goto(config.base_url, wait_until="domcontentloaded")
    save_snapshot(page, run_dir, "home_loaded")

    _clear_interstitials(page, config, logger)
    if _is_logged_in_session(page, config):
        logger.info("Session already active; skipping login")
        save_snapshot(page, run_dir, "login_skipped_session_active")
        return page

    _prepare_login_page(page, config, logger, run_dir)
    if _is_logged_in_session(page, config):
        logger.info("Session already active after preparation; skipping login")
        save_snapshot(page, run_dir, "login_skipped_session_active")
        return page
    save_snapshot(page, run_dir, "login_ready")

    logger.info("Submitting username and password")
    fill_first_available(
        page,
        config.caixa_username,
        _username_selectors(config),
        timeout_ms=6000,
    )

    current_step = "password" if _password_visible(page, config) else "unknown"

    if current_step != "password":
        logger.info("Password field not visible yet, advancing login step")
        cpf_locator = find_visible_locator_by_selectors(page, _username_selectors(config), timeout_ms=1200)
        if cpf_locator is not None:
            try:
                cpf_locator.press("Tab", timeout=1000)
            except (PlaywrightTimeoutError, PlaywrightError):
                pass

        if not _click_login_next_button(page, config, logger):
            raise AutomationError(f"Unable to click login next button. current_url={page.url}")

        page, current_step = _wait_for_login_step(page, config, logger, timeout_ms=30000)
        save_snapshot(page, run_dir, "login_after_next")

    if current_step == "otp":
        logger.info("Waiting for login email code")
        otp = input("Enter login email code: ").strip()
        if not otp:
            raise AutomationError("Login email OTP cannot be empty")

        fill_first_available(
            page,
            otp,
            _login_otp_selectors(config),
            timeout_ms=10000,
        )
        page = _submit_login_otp(page, config, logger)
        save_snapshot(page, run_dir, "login_otp_submitted")

        page, after_otp_step = _wait_for_password_or_login_completion(page, config, logger, timeout_ms=30000)
        if after_otp_step == "done":
            logger.info("Login step completed after OTP challenge")
            return page

        page = _resolve_active_page(page, logger)
        if not _is_login_domain(page):
            logger.info("Left login domain after OTP; skipping password submit")
            return page
        if not _password_visible(page, config):
            logger.info("Password field no longer visible after OTP; skipping password submit")
            return page

        fill_first_available(
            page,
            config.caixa_password,
            _password_selectors(config),
            timeout_ms=10000,
        )
        page = _resolve_active_page(page, logger)
        if not _is_login_domain(page):
            logger.info("Left login domain before post-OTP password submit click")
            return page
        if not _click_login_submit_button(page, config, logger):
            page = _resolve_active_page(page, logger)
            if not _is_login_domain(page):
                logger.info("Login finished while trying post-OTP password submit click")
                return page
            raise AutomationError(f"Unable to click login submit button after OTP. current_url={page.url}")
        save_snapshot(page, run_dir, "login_submitted")
        logger.info("Login step completed after OTP + password")
        return page

    fill_first_available(
        page,
        config.caixa_password,
        _password_selectors(config),
        timeout_ms=10000,
    )
    page = _resolve_active_page(page, logger)
    if not _is_login_domain(page):
        logger.info("Left login domain before password submit click")
        return page
    if not _click_login_submit_button(page, config, logger):
        raise AutomationError(f"Unable to click login submit button. current_url={page.url}")
    save_snapshot(page, run_dir, "login_submitted")

    if _login_otp_visible(page, config):
        logger.info("Waiting for login OTP input")
        otp = input("Enter login email code: ").strip()
        if not otp:
            raise AutomationError("Login email OTP cannot be empty")

        fill_first_available(
            page,
            otp,
            _login_otp_selectors(config),
            timeout_ms=10000,
        )
        page = _submit_login_otp(page, config, logger)
        save_snapshot(page, run_dir, "login_otp_submitted")

    if page.url == config.base_url:
        logger.info("Login appears successful")
        return page

    if "login" in page.url.lower():
        raise AutomationError("Still on login page after OTP submission")

    logger.info("Login step completed, current URL: %s", page.url)
    return page
