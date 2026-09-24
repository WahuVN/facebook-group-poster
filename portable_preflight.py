from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

APP_DATA_RELATIVE = Path("WAHU") / "FacebookPublisher"
REQUIRED_MODULES = ("dotenv", "playwright.sync_api")
OPTIONAL_MODULES = ("windnd",)


def local_app_data_root() -> Path:
    raw = os.getenv("LOCALAPPDATA", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "AppData" / "Local").resolve()


def app_data_dir() -> Path:
    return local_app_data_root() / APP_DATA_RELATIVE


def _writable_directory(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".wahu-preflight-", dir=path, delete=False
        ) as handle:
            probe = Path(handle.name)
            handle.write("ok")
        probe.unlink(missing_ok=True)
        return True, "writable"
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def _module_status(name: str) -> dict[str, Any]:
    try:
        importlib.import_module(name)
        return {"name": name, "ok": True}
    except Exception as error:
        return {"name": name, "ok": False, "error": type(error).__name__}


def _browser_runtime_status() -> dict[str, Any]:
    configured = os.getenv("BROWSER_EXECUTABLE_PATH", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        return {
            "ok": candidate.is_file(),
            "source": "BROWSER_EXECUTABLE_PATH",
            "configured": True,
            "pathExists": candidate.is_file(),
        }

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            candidate = Path(playwright.chromium.executable_path)
        return {
            "ok": candidate.is_file(),
            "source": "playwright-cache",
            "configured": False,
            "pathExists": candidate.is_file(),
        }
    except Exception as error:
        return {
            "ok": False,
            "source": "playwright-cache",
            "configured": False,
            "pathExists": False,
            "error": type(error).__name__,
        }


def build_report() -> dict[str, Any]:
    fatal: list[str] = []
    warnings: list[str] = []

    if sys.platform != "win32":
        fatal.append("Windows là nền tảng được hỗ trợ cho gói portable này.")

    writable, writable_detail = _writable_directory(app_data_dir())
    if not writable:
        fatal.append("Không ghi được thư mục dữ liệu cục bộ của ứng dụng.")

    required = [_module_status(name) for name in REQUIRED_MODULES]
    missing_required = [item["name"] for item in required if not item["ok"]]
    if missing_required:
        fatal.append("Thiếu module runtime bắt buộc: " + ", ".join(missing_required))

    optional = [_module_status(name) for name in OPTIONAL_MODULES]
    missing_optional = [item["name"] for item in optional if not item["ok"]]
    if missing_optional:
        warnings.append("Thiếu module tùy chọn: " + ", ".join(missing_optional))

    browser = _browser_runtime_status() if not missing_required else {
        "ok": False,
        "source": "unavailable",
        "configured": False,
        "pathExists": False,
    }
    if not browser["ok"]:
        warnings.append(
            "Chưa tìm thấy browser runtime. Cấu hình BROWSER_EXECUTABLE_PATH hoặc cài Playwright Chromium "
            "bằng setup nguồn trước khi chạy tác vụ thật."
        )

    return {
        "schemaVersion": 1,
        "product": "FacebookPublisher",
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "appData": {"ok": writable, "detail": writable_detail},
        "modules": {"required": required, "optional": optional},
        "browser": browser,
        "fatal": fatal,
        "warnings": warnings,
        "ok": not fatal,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, path)


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False, indent=2, sort_keys=True))
