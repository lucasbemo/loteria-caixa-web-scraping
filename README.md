# Caixa Loterias Automation (Playwright)

Automates this flow:

1. Open Caixa Loterias site.
2. Login with username and password from `.env`.
3. Pause for login email code (manual input in terminal).
4. Open favorites cart and add one pre-existing item by exact visible text.
5. Go to checkout and validate expected total.
6. Select saved card or fill card form from `.env`.
7. Pause for payment challenge code (manual input in terminal).
8. Submit and report result.

## Requirements

- Python 3.11+
- Chromium dependencies for Playwright

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
```

Fill `.env` with real values.

## Run

```bash
python -m src.main
```

During execution, the script will ask for:

- `Enter login email code:`
- `Enter payment code:`

Artifacts are saved to `runs/<timestamp>/`:

- `run.log`
- `screenshots/*.png`

## Notes

- Secrets are read only from `.env`.
- OTP codes are entered manually and are not stored in `.env`.
- If selectors change, adjust optional selector env vars in `.env`.
- Login now tries to auto-handle common interstitials (cookie consent, age gate, and top-right "Acessar") before filling credentials, and supports CPF -> "Próximo" -> senha flows.
