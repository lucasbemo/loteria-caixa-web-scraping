from __future__ import annotations

import logging
import re
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from ..config import AppConfig
from ..errors import AutomationError
from ..utils.snapshots import save_snapshot
from ..utils.ui import (
    any_visible_by_selectors,
    click_by_text,
    fill_first_available,
    normalize_money,
    text_exists,
    visible_locator_by_selectors,
)


def _try_click(locator, timeout_ms: int = 2200) -> bool:
    try:
        locator.wait_for(state="visible", timeout=timeout_ms)
        locator.click(timeout=timeout_ms)
        return True
    except (PlaywrightTimeoutError, PlaywrightError):
        return False


def _page_is_closed(page: Page) -> bool:
    try:
        return page.is_closed()
    except PlaywrightError:
        return True


def _cart_context_changed(page: Page, before_url: str) -> bool:
    try:
        current_url = page.url or ""
    except PlaywrightError:
        current_url = ""

    if current_url and current_url != before_url:
        return True

    if text_exists(page, "Carrinhos Favoritos", exact=False, timeout_ms=500):
        if page.locator("table tbody tr").count() > 0:
            return False

    return text_exists(page, "Finalizar", exact=False, timeout_ms=500) or text_exists(
        page, "Carrinho", exact=False, timeout_ms=500
    )


def _is_cart_page(page: Page) -> bool:
    return (
        text_exists(page, "Carrinho de Apostas", exact=False, timeout_ms=900)
        or text_exists(page, "Apostas Individuais", exact=False, timeout_ms=900)
        or text_exists(page, "Ir pra pagamento", exact=False, timeout_ms=900)
    )


def _is_favorites_page(page: Page) -> bool:
    return text_exists(page, "Carrinhos Favoritos", exact=False, timeout_ms=700)


def _is_home_products_page(page: Page) -> bool:
    return text_exists(page, "Todos os produtos", exact=False, timeout_ms=700)


def _is_checkout_or_payment_page(page: Page, config: AppConfig) -> bool:
    try:
        current_url = page.url or ""
    except PlaywrightError:
        current_url = ""

    if "pagamento" in current_url.lower() or "#/carrinho/pagamento" in current_url.lower():
        return True

    if text_exists(page, "Forma de Pagamento", exact=False, timeout_ms=700):
        return True

    if _is_confirmation_modal_visible(page) and text_exists(page, "Confirma", exact=False, timeout_ms=700):
        return True

    if _is_home_products_page(page) or _is_favorites_page(page) or _is_cart_page(page):
        return False

    if text_exists(page, config.pay_submit_text or "Pagar", exact=False, timeout_ms=700):
        return True

    payment_fields = [
        config.card_number_selector,
        config.card_holder_selector,
        config.card_exp_month_selector,
        config.card_exp_year_selector,
        config.card_cvv_selector,
        "input[name='cardNumber']",
        "input[autocomplete='cc-number']",
        "input[name='cvv']",
        "input[autocomplete='cc-csc']",
    ]
    return any_visible_by_selectors(page, payment_fields, timeout_ms=700)


def _header_cart_click_candidates(page: Page):
    return [
        page.locator("xpath=//nav[@id='menuPrincipal']//*[self::a or self::button][contains(normalize-space(.), 'Minha Conta')]/preceding-sibling::*[self::a or self::button][1]").first,
        page.locator("xpath=//nav[@id='menuPrincipal']//*[self::a or self::button][contains(normalize-space(.), 'Minha Conta')]/ancestor::*[self::div or self::li][1]//*[self::a or self::button][.//*[contains(@class,'shopping-cart')] or contains(normalize-space(.),'0') or contains(normalize-space(.),'1') or contains(normalize-space(.),'2') or contains(normalize-space(.),'3') or contains(normalize-space(.),'4') or contains(normalize-space(.),'5') or contains(normalize-space(.),'6') or contains(normalize-space(.),'7') or contains(normalize-space(.),'8') or contains(normalize-space(.),'9')][1]").first,
        page.locator("xpath=//nav[@id='menuPrincipal']//*[self::a or self::button][.//i[contains(@class,'shopping-cart')] or .//*[contains(@class,'shopping-cart')]]").first,
        page.locator("xpath=//nav[@id='menuPrincipal']//*[self::a or self::button][contains(@href,'carrinho') or contains(@href,'cart')]").first,
    ]


def _navigate_cart_routes(page: Page, logger: logging.Logger) -> bool:
    try:
        current = page.url or ""
    except PlaywrightError:
        current = ""

    if not current:
        return False

    base = current.split("#", 1)[0]
    route_candidates = [
        f"{base}#/carrinho",
        f"{base}#/cart",
        f"{base}#/checkout",
    ]

    for target in route_candidates:
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=15000)
        except PlaywrightError:
            continue

        if text_exists(page, "Carrinhos Favoritos", exact=False, timeout_ms=700):
            continue
        if text_exists(page, "Finalizar", exact=False, timeout_ms=1200) or text_exists(
            page, "Pagamento", exact=False, timeout_ms=1200
        ):
            logger.info("Opened cart/checkout by direct route: %s", target)
            return True

    return False


def _open_cart(page: Page, config: AppConfig, logger: logging.Logger) -> bool:
    try:
        before_url = page.url or ""
    except PlaywrightError:
        before_url = ""

    if config.cart_entry_selector and config.cart_entry_selector.strip():
        if _try_click(page.locator(config.cart_entry_selector).first):
            page.wait_for_timeout(500)
            if _cart_context_changed(page, before_url):
                logger.info("Opened cart using CART_ENTRY_SELECTOR")
                return True

    for candidate in _header_cart_click_candidates(page):
        if _try_click(candidate):
            page.wait_for_timeout(600)
            if _is_cart_page(page) or _cart_context_changed(page, before_url):
                logger.info("Opened cart using header cart control")
                return True

    for candidate in _header_cart_click_candidates(page):
        if _try_click(candidate):
            page.wait_for_timeout(900)
            if _is_cart_page(page):
                logger.info("Opened cart using header cart control (retry)")
                return True

    cart_regex = re.compile(r"\bcarrinho\b(?!s?\s+favorit)|\bcart\b", re.IGNORECASE)
    cart_selectors = [
        "nav .navbar-right a:has(.fa-shopping-cart)",
        "nav .navbar-right button:has(.fa-shopping-cart)",
        "nav .navbar-right a:has(i.fa-shopping-cart)",
        "nav .navbar-right button:has(i.fa-shopping-cart)",
        "a:has(.fa-shopping-cart)",
        "button:has(.fa-shopping-cart)",
        "a:has(i.fa-shopping-cart)",
        "button:has(i.fa-shopping-cart)",
        "a[href*='carrinho' i]",
        "a[href*='cart' i]",
        "[data-testid*='cart' i]",
        "[class*='cart' i] a",
    ]
    for selector in cart_selectors:
        if _try_click(page.locator(selector).first):
            page.wait_for_timeout(500)
            if _is_cart_page(page) or _cart_context_changed(page, before_url):
                logger.info("Opened cart using selector: %s", selector)
                return True

    for candidate in [
        page.get_by_role("link", name=cart_regex).first,
        page.get_by_role("button", name=cart_regex).first,
    ]:
        if _try_click(candidate):
            page.wait_for_timeout(500)
            if _is_cart_page(page):
                logger.info("Opened cart by role regex")
                return True

    if config.cart_entry_text and config.cart_entry_text.strip():
        text_regex = re.compile(re.escape(config.cart_entry_text), re.IGNORECASE)
        for candidate in [
            page.get_by_role("link", name=text_regex).first,
            page.get_by_role("button", name=text_regex).first,
            page.get_by_text(text_regex).first,
        ]:
            if _try_click(candidate):
                page.wait_for_timeout(500)
                if _is_cart_page(page):
                    logger.info("Opened cart by text: %s", config.cart_entry_text)
                    return True

    if _navigate_cart_routes(page, logger):
        return True

    return False


def _click_checkout(page: Page, config: AppConfig, logger: logging.Logger) -> bool:
    before_url = ""
    try:
        before_url = page.url or ""
    except PlaywrightError:
        pass

    if config.checkout_button_selector and config.checkout_button_selector.strip():
        if _try_click(page.locator(config.checkout_button_selector).first, timeout_ms=2500):
            page.wait_for_timeout(700)
            if _is_checkout_or_payment_page(page, config):
                logger.info("Opened checkout using CHECKOUT_BUTTON_SELECTOR")
                return True

    explicit_candidates = [
        page.get_by_role("button", name=re.compile(r"ir\s+pra\s+pagamento", re.IGNORECASE)).first,
        page.get_by_role("link", name=re.compile(r"ir\s+pra\s+pagamento", re.IGNORECASE)).first,
        page.locator("button:has-text('Ir pra pagamento')").first,
        page.locator("a:has-text('Ir pra pagamento')").first,
    ]
    for candidate in explicit_candidates:
        if _try_click(candidate, timeout_ms=2500):
            page.wait_for_timeout(700)
            _handle_checkout_confirmation_modal(page, logger)
            if _is_checkout_or_payment_page(page, config):
                logger.info("Opened checkout by explicit payment CTA")
                return True

    checkout_regex = re.compile(r"finalizar|checkout|pagamento|fechar pedido", re.IGNORECASE)
    for candidate in [
        page.get_by_role("button", name=checkout_regex).first,
        page.get_by_role("link", name=checkout_regex).first,
    ]:
        if _try_click(candidate, timeout_ms=2500):
            page.wait_for_timeout(700)
            _handle_checkout_confirmation_modal(page, logger)
            if _is_checkout_or_payment_page(page, config):
                logger.info("Opened checkout by role regex")
                return True

    texts = [config.checkout_button_text, "Ir pra pagamento", "Finalizar", "Pagamento", "Fechar pedido"]
    seen: set[str] = set()
    for text in texts:
        key = (text or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        if _try_click(page.locator(f"button:has-text('{key}')").first, timeout_ms=2000):
            page.wait_for_timeout(700)
            _handle_checkout_confirmation_modal(page, logger)
            if _is_checkout_or_payment_page(page, config):
                logger.info("Opened checkout by button text: %s", key)
                return True
        if _try_click(page.locator(f"a:has-text('{key}')").first, timeout_ms=2000):
            page.wait_for_timeout(700)
            _handle_checkout_confirmation_modal(page, logger)
            if _is_checkout_or_payment_page(page, config):
                logger.info("Opened checkout by link text: %s", key)
                return True

    try:
        current_url = page.url or ""
    except PlaywrightError:
        current_url = ""
    if before_url and current_url and current_url != before_url:
        logger.info("Checkout click changed URL but payment context not detected: %s", current_url)

    return False


def _payment_submit_visible(page: Page, config: AppConfig) -> bool:
    labels = [config.pay_submit_text, "Continuar", "Pagar", "Concluir", "Finalizar", "Confirmar"]
    for label in labels:
        key = (label or "").strip()
        if key and text_exists(page, key, exact=False, timeout_ms=500):
            return True
    return False


def _wait_for_payment_submit(page: Page, config: AppConfig, timeout_ms: int = 8000) -> bool:
    polls = max(1, timeout_ms // 250)
    for _ in range(polls):
        if _payment_submit_visible(page, config):
            return True
        page.wait_for_timeout(250)
    return False


def _click_saved_card_text(page: Page, logger: logging.Logger, last4: str | None = None) -> bool:
    if last4:
        digits = "".join(ch for ch in last4 if ch.isdigit())[-4:]
        if len(digits) == 4:
            specific = page.get_by_text(re.compile(rf"(?:\*{{2,}}\s*)?{re.escape(digits)}\b")).first
            if _try_click(specific, timeout_ms=2200):
                logger.info("Selected saved card by number text ending in %s", digits)
                page.wait_for_timeout(500)
                return True

    generic = page.get_by_text(re.compile(r"\*{2,}\s*\d{4}")).first
    if _try_click(generic, timeout_ms=2200):
        logger.info("Selected saved card by visible number text")
        page.wait_for_timeout(500)
        return True

    return False


def _select_saved_card_by_last4(page: Page, last4: str, logger: logging.Logger) -> bool:
    digits = "".join(ch for ch in last4 if ch.isdigit())
    if len(digits) < 4:
        return False

    suffix = digits[-4:]
    pattern = re.compile(rf"(?:\*{{2,}}\s*)?{re.escape(suffix)}\b")

    if _click_saved_card_text(page, logger, suffix):
        return True

    row_candidates = [
        page.locator("tr,li,div").filter(has_text=pattern).first,
        page.locator(
            "xpath=//*[contains(normalize-space(.), 'Cartão de crédito')]/following::*[self::tr or self::li or self::div][contains(normalize-space(.), '"
            + suffix
            + "')][1]"
        ).first,
    ]

    for row in row_candidates:
        try:
            row.wait_for(state="visible", timeout=1500)
        except (PlaywrightTimeoutError, PlaywrightError):
            continue

        action_candidates = [
            row.locator("xpath=.//*[self::button or self::a][.//*[contains(@class,'angle-right') or contains(@class,'chevron-right') or contains(@class,'arrow-right')]]").first,
            row.locator("xpath=.//*[self::button or self::a][not(.//*[contains(@class,'trash') or contains(@class,'remove') or contains(@class,'delete')])][last()]").first,
            row.locator("xpath=.//*[self::button or self::a][contains(@aria-label, 'sele') or contains(@title, 'sele') or contains(@title, 'usar') or contains(@title, 'continuar')]").first,
            row,
        ]
        for candidate in action_candidates:
            if _try_click(candidate, timeout_ms=2200):
                logger.info("Selected saved card ending in %s", suffix)
                page.wait_for_timeout(500)
                return True

    text_locator = page.get_by_text(pattern).first
    try:
        text_locator.wait_for(state="visible", timeout=1500)
        clickable_ancestor = text_locator.locator(
            "xpath=ancestor::*[self::button or self::a or @role='button' or self::label or self::li or self::tr][1]"
        ).first
        if _try_click(clickable_ancestor, timeout_ms=2000):
            logger.info("Selected saved card ending in %s via ancestor click", suffix)
            return True
    except (PlaywrightTimeoutError, PlaywrightError):
        pass

    return False


def _select_any_saved_card(page: Page, logger: logging.Logger) -> bool:
    saved_card_pattern = re.compile(r"\*{2,}\s*\d{4}")

    if _click_saved_card_text(page, logger):
        return True

    candidates = [
        page.locator("button,a,label,li,tr,div").filter(has_text=saved_card_pattern).first,
        page.locator(
            "xpath=//*[contains(normalize-space(.), 'Cartão de crédito')]/following::*[self::button or self::a or self::label or self::li or self::tr or self::div][contains(normalize-space(.), '****')][1]"
        ).first,
    ]

    for candidate in candidates:
        if _try_click(candidate, timeout_ms=2500):
            logger.info("Selected first available saved card")
            return True

    card_text = page.get_by_text(saved_card_pattern).first
    try:
        card_text.wait_for(state="visible", timeout=1500)
        clickable_ancestor = card_text.locator(
            "xpath=ancestor::*[self::button or self::a or @role='button' or self::label or self::li or self::tr][1]"
        ).first
        if _try_click(clickable_ancestor, timeout_ms=2000):
            logger.info("Selected first available saved card via ancestor click")
            return True
    except (PlaywrightTimeoutError, PlaywrightError):
        pass

    return False


def _click_payment_submit_button(page: Page, config: AppConfig, logger: logging.Logger) -> bool:
    try:
        page.mouse.wheel(0, 1200)
    except PlaywrightError:
        pass

    if config.pay_submit_selector and config.pay_submit_selector.strip():
        if _try_click(page.locator(config.pay_submit_selector).first, timeout_ms=2500):
            logger.info("Clicked payment submit by PAY_SUBMIT_SELECTOR")
            return True

    submit_regex = re.compile(r"continuar|pagar|concluir|finalizar|confirmar", re.IGNORECASE)
    for candidate in [
        page.get_by_role("button", name=submit_regex).first,
        page.get_by_role("link", name=submit_regex).first,
        page.locator("button:has-text('Continuar')").first,
        page.locator("a:has-text('Continuar')").first,
        page.locator("button:has-text('Pagar')").first,
        page.locator("button:has-text('Concluir')").first,
        page.locator("button:has-text('Finalizar')").first,
        page.locator("a:has-text('Pagar')").first,
    ]:
        if _try_click(candidate, timeout_ms=2200):
            logger.info("Clicked payment submit by text/role")
            return True

    return False


def _payment_otp_modal_input_selectors(config: AppConfig) -> list[str]:
    return [
        config.payment_otp_input_selector,
        "input[data-checkout='securityCodeModal']",
        "input[name='otp']",
        "input[name='codigo']",
        "input[name*='codigo']",
        "input[id*='codigo']",
        "input[placeholder*='C\u00f3digo de Seguran\u00e7a']",
        "input[placeholder*='codigo de seguranca']",
        "input[placeholder*='C\u00f3digo']",
        "input[placeholder*='codigo']",
        "input[inputmode='numeric']",
        "input[type='tel']",
        "input[type='text']",
    ]


def _find_visible_in_scope(scope: Locator, selectors: list[str], timeout_ms: int = 1200) -> Locator | None:
    for selector in selectors:
        if not selector or not selector.strip():
            continue
        locator = scope.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except (PlaywrightTimeoutError, PlaywrightError):
            continue
    return None


def _otp_submit_feedback_detected(page: Page) -> bool:
    status_regex = re.compile(
        r"processando|aguarde|analisando|confirmando|pagamento realizado|pagamento recusado|sucesso|falha|erro|comprovante",
        re.IGNORECASE,
    )
    try:
        return page.get_by_text(status_regex).first.is_visible(timeout=250)
    except PlaywrightError:
        return False


def _wait_for_otp_submit_evidence(page: Page, timeout_ms: int = 3500, poll_ms: int = 250) -> str:
    polls = max(1, timeout_ms // poll_ms)
    for _ in range(polls):
        if _otp_submit_feedback_detected(page):
            return "feedback"
        page.wait_for_timeout(poll_ms)

    if _otp_submit_feedback_detected(page):
        return "feedback"
    if _otp_strict_modal_still_visible(page):
        return "modal_open"
    return "closed_no_feedback"


def _fill_payment_otp_in_modal(page: Page, config: AppConfig, otp: str, logger: logging.Logger) -> None:
    modal = _find_strict_payment_otp_modal(page)
    if modal is None:
        raise AutomationError("Strict payment OTP modal '#confirm-cancel-cvv' not found; refusing to fill code outside modal")

    otp_input = _find_visible_in_scope(modal, _payment_otp_modal_input_selectors(config), timeout_ms=1400)
    if otp_input is None:
        raise AutomationError("Payment OTP input is not visible inside confirmation modal")

    otp_input.fill(otp)
    logger.info("Filled payment OTP inside modal")


def _find_payment_otp_modal(page: Page):
    if _page_is_closed(page):
        return None

    strict_modal = page.locator("#confirm-cancel-cvv").first
    try:
        if strict_modal.is_visible(timeout=500):
            return strict_modal
    except PlaywrightError:
        pass

    modal_text = re.compile(r"c[oó]digo de seguran|confirma o pagamento", re.IGNORECASE)
    modal_selectors = ["[role='dialog']", ".modal-dialog", ".modal", ".ui-dialog", ".swal2-popup"]
    for selector in modal_selectors:
        modal = page.locator(selector).first
        try:
            modal.wait_for(state="visible", timeout=700)
        except (PlaywrightTimeoutError, PlaywrightError):
            continue

        has_text = False
        has_otp_input = False
        has_confirm = False
        try:
            has_text = modal.get_by_text(modal_text).first.is_visible(timeout=300)
        except PlaywrightError:
            has_text = False
        try:
            has_otp_input = (
                modal.locator("input[data-checkout='securityCodeModal']").first.is_visible(timeout=300)
                or modal.locator("input[name='otp']").first.is_visible(timeout=300)
                or modal.locator("input[name*='codigo']").first.is_visible(timeout=300)
                or modal.locator("input[id*='codigo']").first.is_visible(timeout=300)
                or modal.locator("input[placeholder*='Código']").first.is_visible(timeout=300)
                or modal.locator("input[placeholder*='codigo']").first.is_visible(timeout=300)
            )
        except PlaywrightError:
            has_otp_input = False
        try:
            has_confirm = (
                modal.locator("#confirmarModalConfirmacao").first.is_visible(timeout=300)
                or modal.locator("button:has-text('Confirmar')").first.is_visible(timeout=300)
            )
        except PlaywrightError:
            has_confirm = False

        if (has_text and has_confirm) or has_otp_input:
            return modal

    return None


def _find_strict_payment_otp_modal(page: Page):
    if _page_is_closed(page):
        return None
    strict_modal = page.locator("#confirm-cancel-cvv").first
    try:
        strict_modal.wait_for(state="visible", timeout=700)
        return strict_modal
    except (PlaywrightTimeoutError, PlaywrightError):
        return None


def _otp_modal_submitted(page: Page) -> bool:
    return _otp_submit_feedback_detected(page)


def _otp_strict_modal_still_visible(page: Page) -> bool:
    if _page_is_closed(page):
        return False
    modal = _find_strict_payment_otp_modal(page)
    if modal is None:
        return False
    try:
        return modal.is_visible(timeout=300)
    except PlaywrightError:
        return False


def _looks_like_modal_dismiss_action(candidate: Locator) -> bool:
    confirm_regex = re.compile(
        r"confirmar|confirmo|continuar|enviar|validar|pagar|concluir|prosseguir|finalizar|ok",
        re.IGNORECASE,
    )
    dismiss_regex = re.compile(
        r"\b(fechar|cancelar|voltar|corrigir|nao|n\u00e3o|close|dismiss|btn-close|modal-close)\b|(^|\s)x(\s|$)",
        re.IGNORECASE,
    )
    snippets: list[str] = []

    for getter in [
        lambda: candidate.inner_text(timeout=250),
        lambda: candidate.get_attribute("value"),
        lambda: candidate.get_attribute("aria-label"),
        lambda: candidate.get_attribute("title"),
        lambda: candidate.get_attribute("id"),
        lambda: candidate.get_attribute("class"),
        lambda: candidate.get_attribute("name"),
        lambda: candidate.get_attribute("data-dismiss"),
        lambda: candidate.get_attribute("data-bs-dismiss"),
        lambda: candidate.get_attribute("data-action"),
        lambda: candidate.get_attribute("onclick"),
    ]:
        try:
            value = getter()
        except PlaywrightError:
            value = None
        if value and value.strip():
            snippets.append(value.strip())

    combined = " ".join(snippets)
    if not combined:
        return False

    looks_confirm_action = confirm_regex.search(combined) is not None and dismiss_regex.search(combined) is None

    for hard_dismiss_attr in ["data-dismiss", "data-bs-dismiss"]:
        try:
            attr_value = candidate.get_attribute(hard_dismiss_attr)
        except PlaywrightError:
            attr_value = None
        if attr_value and "modal" in attr_value.lower() and not looks_confirm_action:
            return True

    return dismiss_regex.search(combined) is not None and not looks_confirm_action


def _describe_click_candidate(candidate: Locator) -> str:
    snippets: list[str] = []
    fields = [
        "id",
        "class",
        "name",
        "aria-label",
        "title",
        "value",
        "data-dismiss",
        "data-bs-dismiss",
        "type",
    ]
    for field in fields:
        try:
            value = candidate.get_attribute(field)
        except PlaywrightError:
            value = None
        if value and value.strip():
            snippets.append(f"{field}={value.strip()}")
    try:
        text = candidate.inner_text(timeout=250)
    except PlaywrightError:
        text = ""
    text = " ".join(text.split())
    if text:
        snippets.append(f"text={text[:80]}")
    return "; ".join(snippets) if snippets else "no-metadata"


def _click_payment_otp_submit_button(page: Page, config: AppConfig, logger: logging.Logger) -> bool:
    if _page_is_closed(page):
        return False

    modal = _find_strict_payment_otp_modal(page)
    if modal is None:
        logger.info("Strict OTP modal '#confirm-cancel-cvv' not visible; refusing submit click outside modal")
        return False

    if config.payment_otp_submit_selector and config.payment_otp_submit_selector.strip():
        sel = modal.locator(config.payment_otp_submit_selector)
        try:
            count = sel.count()
        except PlaywrightError:
            count = 0
        for idx in range(count):
            candidate = sel.nth(idx)
            if _looks_like_modal_dismiss_action(candidate):
                logger.info("Skipping OTP modal candidate that looks like dismiss action: %s", _describe_click_candidate(candidate))
                continue
            if _try_click(candidate, timeout_ms=2200):
                logger.info(
                    "Clicked payment OTP submit inside modal by configured selector (%s)",
                    _describe_click_candidate(candidate),
                )
                return True
            try:
                candidate.wait_for(state="visible", timeout=600)
                candidate.click(timeout=1800, force=True)
                logger.info(
                    "Clicked payment OTP submit inside modal by configured selector (force) (%s)",
                    _describe_click_candidate(candidate),
                )
                return True
            except (PlaywrightTimeoutError, PlaywrightError):
                continue

    modal_locators = [
        modal.locator("#confirmarModalConfirmacao"),
        modal.get_by_role("button", name=re.compile(r"confirmar", re.IGNORECASE)),
        modal.locator("button:has-text('Confirmar')"),
        modal.locator("a:has-text('Confirmar')"),
        modal.locator("input[type='button'][value*='Confirmar']"),
        modal.locator("input[type='submit'][value*='Confirmar']"),
        modal.locator("button").filter(has_text=re.compile(r"confirmar|continuar|enviar|validar", re.IGNORECASE)),
    ]
    for loc in modal_locators:
        try:
            count = loc.count()
        except PlaywrightError:
            count = 0
        for idx in range(count):
            candidate = loc.nth(idx)
            try:
                candidate.wait_for(state="visible", timeout=900)
            except (PlaywrightTimeoutError, PlaywrightError):
                continue

            if _looks_like_modal_dismiss_action(candidate):
                logger.info("Skipping OTP modal candidate that looks like dismiss action: %s", _describe_click_candidate(candidate))
                continue

            if _try_click(candidate, timeout_ms=2400):
                page.wait_for_timeout(450)
                logger.info("Clicked payment OTP submit inside modal (%s)", _describe_click_candidate(candidate))
                return True
            try:
                candidate.click(timeout=1800, force=True)
                page.wait_for_timeout(450)
                logger.info("Clicked payment OTP submit inside modal (force) (%s)", _describe_click_candidate(candidate))
                return True
            except (PlaywrightTimeoutError, PlaywrightError):
                try:
                    candidate.evaluate("el => el.click()")
                    page.wait_for_timeout(450)
                    logger.info(
                        "Clicked payment OTP submit inside modal (evaluate) (%s)",
                        _describe_click_candidate(candidate),
                    )
                    return True
                except PlaywrightError:
                    continue

    return False


def _is_confirmation_modal_visible(page: Page) -> bool:
    if _page_is_closed(page):
        return False
    try:
        dialogs = page.locator("[role='dialog']")
        if dialogs.count() > 0 and dialogs.first.is_visible(timeout=300):
            return True
    except PlaywrightError:
        pass

    modal_selectors = [".modal", ".modal-dialog", ".ui-dialog", ".swal2-popup"]
    for selector in modal_selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=300):
                return True
        except PlaywrightError:
            continue
    return False


def _handle_checkout_confirmation_modal(page: Page, logger: logging.Logger, timeout_ms: int = 8000) -> bool:
    if not (
        _is_confirmation_modal_visible(page)
        or text_exists(page, "Confirma", exact=False, timeout_ms=700)
        or text_exists(page, "Valor total", exact=False, timeout_ms=700)
    ):
        return False

    confirm_candidates = [
        page.get_by_role("button", name=re.compile(r"confirmar|confirmo|sim", re.IGNORECASE)).first,
        page.locator("button:has-text('Confirmar')").first,
        page.locator("a:has-text('Confirmar')").first,
        page.get_by_text(re.compile(r"confirmar", re.IGNORECASE)).first,
    ]

    for candidate in confirm_candidates:
        if _try_click(candidate, timeout_ms=2000):
            logger.info("Checkout confirmation modal detected; clicked Confirmar")
            page.wait_for_timeout(500)
            break
    else:
        return False

    max_polls = max(1, timeout_ms // 250)
    for _ in range(max_polls):
        still_visible = _is_confirmation_modal_visible(page)
        still_text = text_exists(page, "Confirma", exact=False, timeout_ms=250)
        if not still_visible and not still_text:
            return True
        page.wait_for_timeout(250)

    return True


def _wait_for_payment_processing_result(
    page: Page, config: AppConfig, logger: logging.Logger, timeout_ms: int = 90000
) -> str:
    logger.info("Waiting payment processing confirmation")
    polls = max(1, timeout_ms // 500)

    success_regex = re.compile(r"pagamento realizado|aposta(s)? realizada(s)?|sucesso|comprovante", re.IGNORECASE)
    failure_regex = re.compile(r"pagamento recusado|n[oã]o autorizado|falha|erro|negado", re.IGNORECASE)
    pending_regex = re.compile(r"processando|aguarde|analisando|confirmando", re.IGNORECASE)

    for _ in range(polls):
        if _page_is_closed(page):
            return "unknown"

        if config.success_text and text_exists(page, config.success_text, exact=False, timeout_ms=400):
            return "success"
        if config.failure_text and text_exists(page, config.failure_text, exact=False, timeout_ms=300):
            return "failure"

        try:
            if page.get_by_text(success_regex).first.is_visible(timeout=300):
                return "success"
        except PlaywrightError:
            pass
        try:
            if page.get_by_text(failure_regex).first.is_visible(timeout=300):
                return "failure"
        except PlaywrightError:
            pass

        otp_modal_open = _is_confirmation_modal_visible(page) and text_exists(
            page, "código de Segurança", exact=False, timeout_ms=250
        )
        pending_visible = False
        try:
            pending_visible = page.get_by_text(pending_regex).first.is_visible(timeout=250)
        except PlaywrightError:
            pending_visible = False

        if otp_modal_open or pending_visible:
            try:
                page.wait_for_timeout(500)
            except PlaywrightError:
                return "unknown"
            continue

        try:
            page.wait_for_timeout(500)
        except PlaywrightError:
            return "unknown"

    return "unknown"


def _validate_total(page: Page, config: AppConfig) -> None:
    expected = normalize_money(config.expected_total)
    if config.total_selector:
        actual_text = page.locator(config.total_selector).first.inner_text(timeout=5000)
        actual = normalize_money(actual_text)
        if expected != actual:
            raise AutomationError(f"Expected total '{config.expected_total}', got '{actual_text.strip()}'")
        return

    if not text_exists(page, config.expected_total, exact=False, timeout_ms=5000):
        raise AutomationError(f"Expected total text not found on page: {config.expected_total}")


def _select_or_fill_card(page: Page, config: AppConfig, logger: logging.Logger) -> None:
    if text_exists(page, "Cartão de crédito", exact=False, timeout_ms=1000):
        _try_click(page.get_by_text(re.compile(r"cart[aã]o de cr[eé]dito", re.IGNORECASE)).first, timeout_ms=1200)

    if config.use_saved_card:
        if config.saved_card_selector:
            page.locator(config.saved_card_selector).first.click()
            logger.info("Selected saved card using selector")
            return
        if config.saved_card_text:
            if _try_click(page.get_by_text(re.compile(re.escape(config.saved_card_text), re.IGNORECASE)).first, timeout_ms=2200):
                logger.info("Selected saved card using text")
                _wait_for_payment_submit(page, config, timeout_ms=5000)
                return
            click_by_text(page, config.saved_card_text, exact=False)
            logger.info("Selected saved card using text fallback")
            _wait_for_payment_submit(page, config, timeout_ms=5000)
            return
        if config.saved_card_last4:
            if _select_saved_card_by_last4(page, config.saved_card_last4, logger):
                _wait_for_payment_submit(page, config, timeout_ms=5000)
                return
            logger.info("SAVED_CARD_LAST4 was provided but no matching card was clickable")
        if _select_any_saved_card(page, logger):
            _wait_for_payment_submit(page, config, timeout_ms=5000)
            return
        logger.info("USE_SAVED_CARD=true but no saved card selector/text provided; falling back to card form")

    fill_first_available(
        page,
        config.card_holder_name,
        [
            config.card_holder_selector,
            "input[name='cardHolder']",
            "input[name='holderName']",
            "input[autocomplete='cc-name']",
        ],
    )
    fill_first_available(
        page,
        config.card_number,
        [
            config.card_number_selector,
            "input[name='cardNumber']",
            "input[autocomplete='cc-number']",
            "input[inputmode='numeric']",
        ],
    )
    fill_first_available(
        page,
        config.card_exp_month,
        [
            config.card_exp_month_selector,
            "input[name='expMonth']",
            "input[autocomplete='cc-exp-month']",
        ],
    )
    fill_first_available(
        page,
        config.card_exp_year,
        [
            config.card_exp_year_selector,
            "input[name='expYear']",
            "input[autocomplete='cc-exp-year']",
            "input[autocomplete='cc-exp']",
        ],
    )
    fill_first_available(
        page,
        config.card_cvv,
        [
            config.card_cvv_selector,
            "input[name='cvv']",
            "input[name='securityCode']",
            "input[autocomplete='cc-csc']",
        ],
    )


def run_checkout_and_payment(page: Page, config: AppConfig, logger: logging.Logger, run_dir: Path) -> None:
    logger.info("Opening cart before checkout")
    if not _open_cart(page, config, logger):
        raise AutomationError("Could not open cart from favorites page")
    if not _is_cart_page(page):
        raise AutomationError("Cart page was not detected after cart open click")
    save_snapshot(page, run_dir, "cart_opened")

    logger.info("Going to checkout")
    if not _click_checkout(page, config, logger):
        raise AutomationError("Could not find checkout action from cart page")
    save_snapshot(page, run_dir, "checkout_opened")

    _handle_checkout_confirmation_modal(page, logger)

    logger.info("Validating expected total")
    _validate_total(page, config)

    _handle_checkout_confirmation_modal(page, logger)

    logger.info("Preparing payment method")
    _select_or_fill_card(page, config, logger)
    save_snapshot(page, run_dir, "payment_form_ready")

    logger.info("Submitting payment")
    _wait_for_payment_submit(page, config, timeout_ms=6000)
    if not _click_payment_submit_button(page, config, logger):
        raise AutomationError("No visible payment submit button found")
    save_snapshot(page, run_dir, "payment_submitted")

    logger.info("Waiting for payment OTP/challenge")
    otp = input("Enter payment code: ").strip()
    if not otp:
        raise AutomationError("Payment OTP cannot be empty")

    _fill_payment_otp_in_modal(page, config, otp, logger)
    page.wait_for_timeout(350)

    attempts = 2
    submitted = False
    closed_without_feedback = False
    for attempt in range(1, attempts + 1):
        if not _click_payment_otp_submit_button(page, config, logger):
            break

        submit_state = _wait_for_otp_submit_evidence(page, timeout_ms=3500, poll_ms=250)
        if submit_state == "feedback" and _otp_modal_submitted(page):
            submitted = True
            break

        if submit_state == "closed_no_feedback":
            logger.error("OTP modal closed without payment processing confirmation markers after submit click")
            closed_without_feedback = True
            break

        if attempt < attempts:
            logger.info("OTP modal still open with no processing feedback; retrying modal confirm click")

    if not submitted:
        if _otp_strict_modal_still_visible(page):
            raise AutomationError("Payment OTP modal is still open after modal-scoped confirm clicks")
        if closed_without_feedback:
            save_snapshot(page, run_dir, "payment_otp_closed_no_feedback")
        raise AutomationError("OTP modal closed without payment processing confirmation markers")

    save_snapshot(page, run_dir, "payment_otp_submitted")

    try:
        visible_locator_by_selectors(page, ["body"], timeout_ms=4000)
    except PlaywrightTimeoutError as exc:
        raise AutomationError("Page did not stabilize after payment OTP submission") from exc

    result = _wait_for_payment_processing_result(page, config, logger, timeout_ms=90000)
    if result == "success":
        logger.info("Payment success text detected")
        save_snapshot(page, run_dir, "payment_success")
        return

    if result == "failure":
        save_snapshot(page, run_dir, "payment_failure")
        raise AutomationError(f"Payment failure text detected: {config.failure_text or 'failure marker found'}")

    logger.info("Payment status not confirmed within wait timeout")
    save_snapshot(page, run_dir, "payment_result_unknown")
    raise AutomationError("Payment was submitted but final confirmation was not detected within timeout")
