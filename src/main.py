from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from .browser import close_browser, start_browser
from .config import load_config
from .errors import AutomationError
from .steps.checkout import run_checkout_and_payment
from .steps.favorites import run_favorites_flow
from .steps.login import run_login
from .utils.logging_utils import build_logger, mask_card
from .utils.snapshots import save_snapshot


def main() -> int:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path("runs") / run_id
    logger = build_logger(run_dir / "run.log")

    try:
        config = load_config()
    except Exception as exc:
        print(f"Config error: {exc}")
        return 2

    logger.info("Starting automation run_id=%s", run_id)
    logger.info("Headless=%s BaseURL=%s", config.headless, config.base_url)
    logger.info("Card ending with %s", mask_card(config.card_number))

    playwright = None
    context = None
    page = None

    try:
        playwright, context, page = start_browser(config)
        page = run_login(page, config, logger, run_dir)
        run_favorites_flow(page, config, logger, run_dir)
        run_checkout_and_payment(page, config, logger, run_dir)
        logger.info("Flow completed")
        print("SUCCESS")
        print(f"Artifacts: {run_dir}")
        return 0
    except AutomationError as exc:
        logger.error("Automation failed: %s", exc)
        if page is not None:
            shot = save_snapshot(page, run_dir, "fatal_error")
            if shot is not None:
                logger.error("Fatal screenshot: %s", shot)
            else:
                logger.error("Fatal screenshot unavailable: page already closed")
        print("FAILED")
        print(f"Reason: {exc}")
        print(f"Artifacts: {run_dir}")
        return 1
    except Exception as exc:
        logger.exception("Unexpected failure: %s", exc)
        if page is not None:
            shot = save_snapshot(page, run_dir, "unexpected_error")
            if shot is not None:
                logger.error("Unexpected screenshot: %s", shot)
            else:
                logger.error("Unexpected screenshot unavailable: page already closed")
        print("FAILED")
        print(f"Reason: unexpected error: {exc}")
        print(f"Artifacts: {run_dir}")
        return 1
    finally:
        if playwright is not None and context is not None:
            close_browser(playwright, context)


if __name__ == "__main__":
    raise SystemExit(main())
