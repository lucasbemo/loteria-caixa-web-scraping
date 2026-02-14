from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required env var: {name}")
    return value


def _optional(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class AppConfig:
    base_url: str
    headless: bool
    slow_mo_ms: int
    timeout_ms: int
    user_data_dir: Path

    caixa_username: str
    caixa_password: str

    favorite_item_name_exact: str
    expected_total: str

    card_holder_name: str
    card_number: str
    card_exp_month: str
    card_exp_year: str
    card_cvv: str
    use_saved_card: bool

    login_username_selector: str
    login_next_selector: str
    login_next_text: str
    login_password_selector: str
    login_submit_selector: str
    login_otp_input_selector: str
    login_otp_submit_selector: str

    cookie_accept_selector: str
    cookie_accept_text: str
    age_gate_prompt_text: str
    age_gate_confirm_selector: str
    age_gate_confirm_text: str
    access_login_selector: str
    access_login_text: str
    enter_site_selector: str
    enter_site_text: str

    account_menu_selector: str
    account_menu_text: str

    favorites_entry_selector: str
    favorites_entry_text: str
    favorites_item_selector: str
    favorites_add_button_selector: str
    favorites_add_button_text: str

    cart_entry_selector: str
    cart_entry_text: str

    checkout_button_selector: str
    checkout_button_text: str
    total_selector: str

    saved_card_selector: str
    saved_card_text: str
    saved_card_last4: str

    card_holder_selector: str
    card_number_selector: str
    card_exp_month_selector: str
    card_exp_year_selector: str
    card_cvv_selector: str
    pay_submit_selector: str
    pay_submit_text: str

    payment_otp_input_selector: str
    payment_otp_submit_selector: str

    success_text: str
    failure_text: str


def load_config() -> AppConfig:
    load_dotenv(override=False)

    return AppConfig(
        base_url=_optional("BASE_URL", "https://www.loteriasonline.caixa.gov.br/silce-web/#/home"),
        headless=_as_bool(os.getenv("HEADLESS"), default=False),
        slow_mo_ms=int(_optional("SLOW_MO_MS", "150")),
        timeout_ms=int(_optional("TIMEOUT_MS", "30000")),
        user_data_dir=Path(_optional("USER_DATA_DIR", ".playwright-profile")),
        caixa_username=_required("CAIXA_USERNAME"),
        caixa_password=_required("CAIXA_PASSWORD"),
        favorite_item_name_exact=_required("FAVORITE_ITEM_NAME_EXACT"),
        expected_total=_required("EXPECTED_TOTAL"),
        card_holder_name=_required("CARD_HOLDER_NAME"),
        card_number=_required("CARD_NUMBER"),
        card_exp_month=_required("CARD_EXP_MONTH"),
        card_exp_year=_required("CARD_EXP_YEAR"),
        card_cvv=_required("CARD_CVV"),
        use_saved_card=_as_bool(os.getenv("USE_SAVED_CARD"), default=True),
        login_username_selector=_optional("LOGIN_USERNAME_SELECTOR"),
        login_next_selector=_optional("LOGIN_NEXT_SELECTOR"),
        login_next_text=_optional("LOGIN_NEXT_TEXT", "Próximo"),
        login_password_selector=_optional("LOGIN_PASSWORD_SELECTOR"),
        login_submit_selector=_optional("LOGIN_SUBMIT_SELECTOR"),
        login_otp_input_selector=_optional("LOGIN_OTP_INPUT_SELECTOR"),
        login_otp_submit_selector=_optional("LOGIN_OTP_SUBMIT_SELECTOR"),
        cookie_accept_selector=_optional("COOKIE_ACCEPT_SELECTOR"),
        cookie_accept_text=_optional("COOKIE_ACCEPT_TEXT", "Aceitar"),
        age_gate_prompt_text=_optional("AGE_GATE_PROMPT_TEXT", "Você tem mais de 18 anos?"),
        age_gate_confirm_selector=_optional("AGE_GATE_CONFIRM_SELECTOR"),
        age_gate_confirm_text=_optional("AGE_GATE_CONFIRM_TEXT", "Sim"),
        access_login_selector=_optional("ACCESS_LOGIN_SELECTOR"),
        access_login_text=_optional("ACCESS_LOGIN_TEXT", "Acessar"),
        enter_site_selector=_optional("ENTER_SITE_SELECTOR"),
        enter_site_text=_optional("ENTER_SITE_TEXT", ""),
        account_menu_selector=_optional("ACCOUNT_MENU_SELECTOR"),
        account_menu_text=_optional("ACCOUNT_MENU_TEXT", "Minha Conta"),
        favorites_entry_selector=_optional("FAVORITES_ENTRY_SELECTOR"),
        favorites_entry_text=_optional("FAVORITES_ENTRY_TEXT", "Carrinhos favoritos"),
        favorites_item_selector=_optional("FAVORITES_ITEM_SELECTOR"),
        favorites_add_button_selector=_optional("FAVORITES_ADD_BUTTON_SELECTOR"),
        favorites_add_button_text=_optional("FAVORITES_ADD_BUTTON_TEXT", "Adicionar"),
        cart_entry_selector=_optional("CART_ENTRY_SELECTOR"),
        cart_entry_text=_optional("CART_ENTRY_TEXT", "Carrinho"),
        checkout_button_selector=_optional("CHECKOUT_BUTTON_SELECTOR"),
        checkout_button_text=_optional("CHECKOUT_BUTTON_TEXT", "Finalizar"),
        total_selector=_optional("TOTAL_SELECTOR"),
        saved_card_selector=_optional("SAVED_CARD_SELECTOR"),
        saved_card_text=_optional("SAVED_CARD_TEXT"),
        saved_card_last4=_optional("SAVED_CARD_LAST4"),
        card_holder_selector=_optional("CARD_HOLDER_SELECTOR"),
        card_number_selector=_optional("CARD_NUMBER_SELECTOR"),
        card_exp_month_selector=_optional("CARD_EXP_MONTH_SELECTOR"),
        card_exp_year_selector=_optional("CARD_EXP_YEAR_SELECTOR"),
        card_cvv_selector=_optional("CARD_CVV_SELECTOR"),
        pay_submit_selector=_optional("PAY_SUBMIT_SELECTOR"),
        pay_submit_text=_optional("PAY_SUBMIT_TEXT", "Pagar"),
        payment_otp_input_selector=_optional("PAYMENT_OTP_INPUT_SELECTOR"),
        payment_otp_submit_selector=_optional("PAYMENT_OTP_SUBMIT_SELECTOR"),
        success_text=_optional("SUCCESS_TEXT", "Pagamento realizado"),
        failure_text=_optional("FAILURE_TEXT", "Pagamento recusado"),
    )
