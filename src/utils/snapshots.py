from __future__ import annotations

from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page


def save_snapshot(page: Page, run_dir: Path, step_name: str) -> Path | None:
    safe_step = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in step_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = run_dir / "screenshots" / f"{timestamp}_{safe_step}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    if page.is_closed():
        return None
    try:
        page.screenshot(path=str(path), full_page=True)
    except PlaywrightError:
        return None
    return path
