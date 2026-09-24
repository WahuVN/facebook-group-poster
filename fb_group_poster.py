import argparse
import csv
import json
import os
import random
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


LogFn = Callable[[str], None]
StopFn = Callable[[], bool]
TickFn = Callable[[int], None]

AUDIENCE_DEFAULT = "default"
AUDIENCE_PUBLIC = "public"
AUDIENCE_FRIENDS = "friends"
AUDIENCE_ONLY_ME = "only_me"

AUDIENCE_LABELS = {
    AUDIENCE_DEFAULT: "Mặc định",
    AUDIENCE_PUBLIC: "Công khai",
    AUDIENCE_FRIENDS: "Bạn bè",
    AUDIENCE_ONLY_ME: "Chỉ mình tôi",
}


@dataclass
class PostTask:
    row_number: int
    group_url: str
    video_path: Path
    caption: str
    schedule_at: datetime | None
    audience: str = AUDIENCE_DEFAULT


@dataclass
class RunnerConfig:
    session_path: Path
    min_delay: int = 20
    max_delay: int = 45
    slow_mo_ms: int = 120
    post_timeout_ms: int = 180000
    headless: bool = False
    locale: str = "vi-VN"
    timezone_id: str = "Asia/Ho_Chi_Minh"
    interactive_login: bool = True
    login_wait_timeout_seconds: int = 0
    browser_executable_path: str | None = None
    user_data_dir: Path | None = None
    profile_directory: str | None = None
    event_log_path: Path | None = None


@dataclass
class RunnerStats:
    total: int = 0
    success: int = 0
    failed: int = 0
    stopped: bool = False


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.75
    max_delay_seconds: float = 4.0
    jitter_seconds: float = 0.25


class AmbiguousPublishStateError(RuntimeError):
    """Submit may have happened, but success could not be confirmed safely."""


_SENSITIVE_KEY_RE = re.compile(
    r"(?:password|passwd|token|secret|cookie|authorization|session|storage[_-]?state|profile)",
    re.I,
)
_SENSITIVE_TEXT_PATTERNS = [
    (re.compile(r"(?i)\b(Bearer)\s+[^\s,;]+"), r"\1 [REDACTED]"),
    (
        re.compile(r"(?i)\b(token|password|passwd|cookie|secret|session)\s*[:=]\s*[^\s,;]+"),
        r"\1=[REDACTED]",
    ),
]


def app_data_dir() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data).expanduser().resolve() / "WAHU" / "FacebookPublisher"
    return Path.home().expanduser().resolve() / ".local" / "share" / "WAHU" / "FacebookPublisher"


def default_session_path() -> Path:
    return app_data_dir() / "session.json"


def default_event_log_path() -> Path:
    return app_data_dir() / "logs" / "events.jsonl"


def error_artifact_path(row_number: int, stamp: str | None = None) -> Path:
    safe_stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    return app_data_dir() / "artifacts" / f"error_{row_number}_{safe_stamp}.png"


def redact_sensitive(value: Any, *, key: str | None = None) -> Any:
    if key and _SENSITIVE_KEY_RE.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact_sensitive(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, str):
        redacted = value
        for pattern, replacement in _SENSITIVE_TEXT_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted
    return value


class JsonlEventLogger:
    def __init__(self, path: Path, *, run_id: str | None = None) -> None:
        self.path = Path(path).expanduser().resolve()
        self.run_id = run_id or uuid.uuid4().hex

    def emit(self, event: str, **fields: Any) -> bool:
        payload: dict[str, Any] = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "event": event,
        }
        payload.update(fields)
        safe_payload = redact_sensitive(payload)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
            return True
        except OSError:
            return False


def save_session_state(context, state_path: Path) -> None:
    """Persist Playwright storage state atomically; default destination is outside the repo."""
    destination = Path(state_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        context.storage_state(path=str(temp_path))
        os.replace(temp_path, destination)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def classify_retry_error(error: Exception) -> str:
    if isinstance(error, AmbiguousPublishStateError):
        return "publish_state_ambiguous"
    if isinstance(error, ConnectionError):
        return "transient_network"

    text = str(error).lower()
    non_retryable_markers = (
        "captcha",
        "checkpoint",
        "permission",
        "not authorized",
        "unauthorized",
        "forbidden",
        "đăng nhập",
        "login",
        "quyền đăng",
        "không tìm thấy",
        "không mở được khung",
        "không bấm được nút đăng",
    )
    if any(marker in text for marker in non_retryable_markers):
        return "non_retryable"

    transient_markers = (
        "net::err_",
        "connection reset",
        "connection aborted",
        "connection refused",
        "network changed",
        "temporarily unavailable",
        "temporary failure",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
    )
    if any(marker in text for marker in transient_markers):
        return "transient_network"
    return "unknown"


def retry_delay_seconds(
    policy: RetryPolicy,
    retry_number: int,
    *,
    random_value: float | None = None,
) -> float:
    exponent = max(retry_number - 1, 0)
    base = min(policy.max_delay_seconds, policy.base_delay_seconds * (2**exponent))
    jitter_source = random.random() if random_value is None else min(max(random_value, 0.0), 1.0)
    return min(policy.max_delay_seconds, base + (policy.jitter_seconds * jitter_source))


def run_with_bounded_retry(
    operation: Callable[[], Any],
    *,
    policy: RetryPolicy | None = None,
    stop_fn: StopFn | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    random_fn: Callable[[], float] = random.random,
    on_retry: Callable[[int, str, float], None] | None = None,
) -> Any:
    """Retry only explicitly transient failures for caller-selected idempotent operations."""
    active_policy = policy or RetryPolicy()
    attempts = max(1, active_policy.max_attempts)

    for attempt in range(1, attempts + 1):
        if _should_stop(stop_fn):
            raise InterruptedError("Đã dừng theo yêu cầu người dùng")
        try:
            return operation()
        except Exception as error:
            error_class = classify_retry_error(error)
            if error_class != "transient_network" or attempt >= attempts:
                raise
            delay = retry_delay_seconds(active_policy, attempt, random_value=random_fn())
            if on_retry:
                on_retry(attempt + 1, error_class, delay)
            if _should_stop(stop_fn):
                raise InterruptedError("Đã dừng theo yêu cầu người dùng") from error
            sleep_fn(delay)

    raise RuntimeError("Retry loop kết thúc ngoài dự kiến")


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_datetime(text: str) -> datetime | None:
    raw = text.strip()
    if not raw:
        return None
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Không parse được schedule_at='{text}'. Dùng định dạng ví dụ: 2026-05-05 21:30"
    )


def normalize_audience(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return AUDIENCE_DEFAULT

    normalized = raw.replace("_", " ").replace("-", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()

    aliases = {
        "default": AUDIENCE_DEFAULT,
        "mac dinh": AUDIENCE_DEFAULT,
        "mặc định": AUDIENCE_DEFAULT,
        "public": AUDIENCE_PUBLIC,
        "cong khai": AUDIENCE_PUBLIC,
        "công khai": AUDIENCE_PUBLIC,
        "friends": AUDIENCE_FRIENDS,
        "friend": AUDIENCE_FRIENDS,
        "ban be": AUDIENCE_FRIENDS,
        "bạn bè": AUDIENCE_FRIENDS,
        "only me": AUDIENCE_ONLY_ME,
        "private": AUDIENCE_ONLY_ME,
        "chi minh toi": AUDIENCE_ONLY_ME,
        "chỉ mình tôi": AUDIENCE_ONLY_ME,
    }

    return aliases.get(normalized, AUDIENCE_DEFAULT)


def audience_label(value: str | None) -> str:
    return AUDIENCE_LABELS.get(normalize_audience(value), AUDIENCE_LABELS[AUDIENCE_DEFAULT])


def load_tasks(csv_path: Path) -> list[PostTask]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file CSV: {csv_path}")

    base_dir = csv_path.parent
    tasks: list[PostTask] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required_columns = {"group_url", "video_path", "caption"}
        missing = required_columns - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"CSV thiếu cột bắt buộc: {', '.join(sorted(missing))}. "
                "Cần có: group_url, video_path, caption"
            )

        for row_number, row in enumerate(reader, start=2):
            enabled = (row.get("enabled") or "1").strip().lower()
            if enabled in {"0", "false", "no", "off"}:
                continue

            group_url = (row.get("group_url") or "").strip()
            video_raw = (row.get("video_path") or "").strip()
            caption = (row.get("caption") or "").replace("\\n", "\n").strip()
            schedule_at = parse_datetime(row.get("schedule_at") or "")
            audience = normalize_audience(row.get("audience"))

            if not group_url:
                raise ValueError(f"Dòng {row_number}: group_url đang trống")
            if not video_raw:
                raise ValueError(f"Dòng {row_number}: video_path đang trống")

            video_path = Path(video_raw)
            if not video_path.is_absolute():
                video_path = (base_dir / video_path).resolve()

            if not video_path.exists():
                raise FileNotFoundError(
                    f"Dòng {row_number}: Không tìm thấy media tại '{video_path}'"
                )

            tasks.append(
                PostTask(
                    row_number=row_number,
                    group_url=group_url,
                    video_path=video_path,
                    caption=caption,
                    schedule_at=schedule_at,
                    audience=audience,
                )
            )

    return tasks


def build_config_from_env(headless_override: bool = False) -> RunnerConfig:
    user_data_dir = os.getenv("BROWSER_USER_DATA_DIR", "").strip()
    session_raw = os.getenv("FB_SESSION_PATH", "").strip()
    event_log_raw = os.getenv("FB_EVENT_LOG_PATH", "").strip()

    return RunnerConfig(
        session_path=(
            Path(session_raw).expanduser().resolve() if session_raw else default_session_path()
        ),
        min_delay=int(os.getenv("MIN_DELAY_SECONDS", "20")),
        max_delay=int(os.getenv("MAX_DELAY_SECONDS", "45")),
        slow_mo_ms=int(os.getenv("SLOW_MO_MS", "120")),
        post_timeout_ms=int(os.getenv("POST_TIMEOUT_MS", "180000")),
        headless=headless_override or env_bool("HEADLESS", False),
        locale=os.getenv("FB_LOCALE", "vi-VN"),
        timezone_id=os.getenv("FB_TIMEZONE", "Asia/Ho_Chi_Minh"),
        interactive_login=True,
        login_wait_timeout_seconds=int(os.getenv("LOGIN_WAIT_TIMEOUT_SECONDS", "0")),
        browser_executable_path=os.getenv("BROWSER_EXECUTABLE_PATH", "").strip() or None,
        user_data_dir=Path(user_data_dir).expanduser().resolve() if user_data_dir else None,
        profile_directory=os.getenv("BROWSER_PROFILE_DIRECTORY", "").strip() or None,
        event_log_path=(
            Path(event_log_raw).expanduser().resolve() if event_log_raw else default_event_log_path()
        ),
    )


def _open_browser_context(playwright, config: RunnerConfig, *, log_fn: LogFn | None = None):
    logger = log_fn or _default_log

    def _launch_non_persistent():
        browser = playwright.chromium.launch(
            headless=config.headless,
            slow_mo=config.slow_mo_ms,
            executable_path=config.browser_executable_path,
        )

        context_options = {
            "locale": config.locale,
            "timezone_id": config.timezone_id,
        }
        if config.session_path.exists():
            context_options["storage_state"] = str(config.session_path)

        context = browser.new_context(**context_options)
        return browser, context

    if config.user_data_dir is not None:
        launch_args: list[str] = []
        if config.profile_directory:
            launch_args.append(f"--profile-directory={config.profile_directory}")

        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(config.user_data_dir),
                executable_path=config.browser_executable_path,
                headless=config.headless,
                slow_mo=config.slow_mo_ms,
                args=launch_args,
                locale=config.locale,
                timezone_id=config.timezone_id,
            )
            return None, context
        except Exception as profile_error:
            logger(
                "[!] Không mở được profile Cốc Cốc thật, chuyển sang chế độ session tạm để tiếp tục."
            )
            logger(f"  - Lý do profile: {profile_error}")

            try:
                browser, context = _launch_non_persistent()
            except Exception as fallback_error:
                raise RuntimeError(
                    "Không mở được cả profile thật lẫn chế độ session tạm. "
                    f"Profile error: {profile_error} | Fallback error: {fallback_error}"
                ) from fallback_error

            if config.session_path.exists():
                logger("[i] Đã dùng session file có sẵn để tiếp tục chạy.")
            else:
                logger("[i] Chưa có session file; hãy đăng nhập Facebook thủ công ở cửa sổ vừa mở.")
            return browser, context

    return _launch_non_persistent()


def _default_log(message: str) -> None:
    print(message)


def _should_stop(stop_fn: StopFn | None) -> bool:
    if stop_fn is None:
        return False
    return bool(stop_fn())


def wait_until(
    schedule_at: datetime,
    *,
    stop_fn: StopFn | None = None,
    tick_fn: TickFn | None = None,
) -> bool:
    initial_remaining = max((schedule_at - datetime.now()).total_seconds(), 0.0)
    deadline = time.monotonic() + initial_remaining

    while True:
        if _should_stop(stop_fn):
            return False

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True

        if tick_fn:
            tick_fn(max(int(remaining + 0.999), 0))
        time.sleep(min(remaining, 0.25))


def dismiss_common_popups(page) -> None:
    candidates = [
        "div[aria-label='Đóng']",
        "div[aria-label='Close']",
        "div[role='button']:has-text('Để sau')",
        "div[role='button']:has-text('Not now')",
        "div[role='button']:has-text('Bỏ qua')",
    ]
    for selector in candidates:
        try:
            target = page.locator(selector).first
            target.wait_for(state="visible", timeout=400)
            if target.is_enabled():
                target.click(timeout=1500)
        except Exception:
            pass


def click_first_visible(page, selectors: list[str], timeout: int = 2500) -> str | None:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout)
            if locator.is_enabled():
                locator.click(timeout=timeout)
                return selector
        except Exception:
            continue
    return None


def is_login_screen(page) -> bool:
    try:
        email_input = page.locator("input[name='email']").first
        password_input = page.locator("input[name='pass']").first
        return email_input.is_visible() and password_input.is_visible()
    except Exception:
        return False


def ensure_logged_in(
    page,
    context,
    state_path: Path,
    *,
    log_fn: LogFn,
    interactive_login: bool,
    login_wait_timeout_seconds: int,
    stop_fn: StopFn | None,
) -> None:
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded")

    if not is_login_screen(page):
        save_session_state(context, state_path)
        log_fn("[OK] Session cục bộ đã được cập nhật an toàn.")
        return

    log_fn("[!] Chưa đăng nhập Facebook trong session hiện tại")
    page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")

    if interactive_login:
        input("[?] Hãy đăng nhập thủ công trên cửa sổ browser rồi nhấn Enter để tiếp tục...")
    else:
        log_fn("[i] Vui lòng đăng nhập thủ công trên browser đang mở...")
        started = time.time()
        while is_login_screen(page):
            if _should_stop(stop_fn):
                raise InterruptedError("Đã dừng theo yêu cầu người dùng")
            if login_wait_timeout_seconds > 0 and (time.time() - started) > login_wait_timeout_seconds:
                raise TimeoutError("Hết thời gian chờ đăng nhập Facebook")
            time.sleep(1)

    page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
    if is_login_screen(page):
        raise RuntimeError("Vẫn chưa đăng nhập, dừng script.")

    save_session_state(context, state_path)
    log_fn("[OK] Session cục bộ đã được cập nhật an toàn.")


def open_composer(page) -> None:
    selectors = [
        "div[role='button']:has-text('Bạn đang nghĩ gì')",
        "div[role='button']:has-text('Bạn viết gì đi')",
        "div[role='button']:has-text('Viết gì đó')",
        "div[role='button']:has-text('Write something')",
        "div[role='button']:has-text(\"What's on your mind\")",
        "div[aria-label='Tạo bài viết']",
        "div[aria-label='Create post']",
        "div[role='button']:has-text('Photo/video')",
        "div[role='button']:has-text('Ảnh/video')",
    ]
    chosen = click_first_visible(page, selectors, timeout=5000)
    if not chosen:
        raise RuntimeError(
            "Không mở được khung tạo bài viết. Hãy kiểm tra quyền đăng ở nhóm/trang cá nhân."
        )


def fill_caption(page, caption: str) -> None:
    targets = [
        "div[role='dialog'] div[role='textbox']",
        "div[role='textbox'][contenteditable='true']",
        "div[aria-label*='Bạn đang nghĩ gì'][role='textbox']",
        "div[aria-label*=\"What's on your mind\"][role='textbox']",
        "div[aria-label='Bạn viết gì đi?'][role='textbox']",
        "div[aria-label=\"What's on your mind?\"][role='textbox']",
    ]
    for selector in targets:
        try:
            box = page.locator(selector).last
            box.wait_for(state="visible", timeout=7000)
            box.click(timeout=2500)
            if caption:
                box.fill(caption)
            return
        except Exception:
            continue
    if caption:
        raise RuntimeError("Không tìm thấy ô nhập nội dung bài viết.")


def upload_video(page, video_path: Path) -> None:
    selectors = [
        "div[role='dialog'] input[type='file']",
        "input[type='file']",
    ]
    for selector in selectors:
        try:
            uploader = page.locator(selector).first
            uploader.set_input_files(str(video_path))
            return
        except Exception:
            continue
    raise RuntimeError("Không tìm thấy input upload media.")


def click_post(page) -> None:
    patterns = [
        re.compile(r"^Đăng$", re.I),
        re.compile(r"^Post$", re.I),
        re.compile(r"Share now", re.I),
    ]

    for pattern in patterns:
        button = page.get_by_role("button", name=pattern).first
        try:
            button.wait_for(state="visible", timeout=45000)
            if button.is_enabled():
                button.click(timeout=3000)
                return
        except Exception:
            continue

    selectors = [
        "div[aria-label='Đăng']",
        "div[aria-label='Post']",
        "div[role='button']:has-text('Đăng')",
        "div[role='button']:has-text('Post')",
    ]
    chosen = click_first_visible(page, selectors, timeout=5000)
    if not chosen:
        raise RuntimeError("Không bấm được nút Đăng/Post.")


def wait_post_done(page, timeout_ms: int) -> None:
    dialog = page.locator("div[role='dialog']").last
    try:
        dialog.wait_for(state="hidden", timeout=timeout_ms)
        return
    except Exception:
        pass

    done_texts = [
        "text=Your post is now published",
        "text=Bài viết của bạn hiện đã được đăng",
        "text=Đã gửi để phê duyệt",
        "text=Sent for approval",
    ]
    for text_selector in done_texts:
        try:
            page.locator(text_selector).first.wait_for(state="visible", timeout=4000)
            return
        except Exception:
            continue

    raise AmbiguousPublishStateError(
        "Không xác nhận được kết quả sau khi bấm Đăng; không tự retry để tránh đăng trùng."
    )


def is_personal_profile_target(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if "facebook.com" not in host:
        return False

    path = unquote((parsed.path or "").strip().lower())
    if not path or path == "/":
        return False
    if path.startswith("/groups"):
        return False
    if path.startswith("/me") or path.startswith("/profile.php") or path.startswith("/people/"):
        return True

    segments = [segment for segment in path.split("/") if segment]
    if len(segments) != 1:
        return False

    blocked = {
        "watch",
        "marketplace",
        "gaming",
        "events",
        "pages",
        "videos",
        "photos",
        "groups",
        "reel",
        "reels",
        "story",
        "stories",
    }
    return segments[0] not in blocked


def set_personal_audience(page, audience: str) -> None:
    mode = normalize_audience(audience)
    if mode == AUDIENCE_DEFAULT:
        return

    open_menu_selectors = [
        "div[role='dialog'] [aria-label*='Đối tượng']",
        "div[role='dialog'] [aria-label*='Audience']",
        "div[role='dialog'] div[role='button']:has-text('Công khai')",
        "div[role='dialog'] div[role='button']:has-text('Bạn bè')",
        "div[role='dialog'] div[role='button']:has-text('Chỉ mình tôi')",
        "div[role='dialog'] div[role='button']:has-text('Public')",
        "div[role='dialog'] div[role='button']:has-text('Friends')",
        "div[role='dialog'] div[role='button']:has-text('Only me')",
    ]
    opened = click_first_visible(page, open_menu_selectors, timeout=3500)
    if not opened:
        raise RuntimeError("Không mở được menu quyền riêng tư của bài đăng trang cá nhân.")

    options_map = {
        AUDIENCE_PUBLIC: [
            "div[role='menuitemradio']:has-text('Công khai')",
            "div[role='radio']:has-text('Công khai')",
            "div[role='button']:has-text('Công khai')",
            "div[role='menuitemradio']:has-text('Public')",
            "div[role='radio']:has-text('Public')",
            "div[role='button']:has-text('Public')",
        ],
        AUDIENCE_FRIENDS: [
            "div[role='menuitemradio']:has-text('Bạn bè')",
            "div[role='radio']:has-text('Bạn bè')",
            "div[role='button']:has-text('Bạn bè')",
            "div[role='menuitemradio']:has-text('Friends')",
            "div[role='radio']:has-text('Friends')",
            "div[role='button']:has-text('Friends')",
        ],
        AUDIENCE_ONLY_ME: [
            "div[role='menuitemradio']:has-text('Chỉ mình tôi')",
            "div[role='radio']:has-text('Chỉ mình tôi')",
            "div[role='button']:has-text('Chỉ mình tôi')",
            "div[role='menuitemradio']:has-text('Only me')",
            "div[role='radio']:has-text('Only me')",
            "div[role='button']:has-text('Only me')",
        ],
    }
    chosen = click_first_visible(page, options_map.get(mode, []), timeout=5000)
    if not chosen:
        raise RuntimeError(f"Không chọn được quyền riêng tư: {audience_label(mode)}")


def post_video_to_group(
    page,
    task: PostTask,
    *,
    post_timeout_ms: int,
    dry_run: bool,
    stop_fn: StopFn | None,
    wait_tick_fn: TickFn | None,
    log_fn: LogFn,
    event_logger: JsonlEventLogger | None = None,
    retry_policy: RetryPolicy | None = None,
) -> bool:
    log_fn(f"\n[>] Dòng {task.row_number} | Đích: {task.group_url}")
    target_is_personal = is_personal_profile_target(task.group_url)
    mode = normalize_audience(task.audience)
    if target_is_personal:
        log_fn(f"  - Quyền riêng tư: {audience_label(mode)}")

    if task.schedule_at:
        log_fn(f"  - Lịch: {task.schedule_at.strftime('%Y-%m-%d %H:%M:%S')}")

        if not wait_until(task.schedule_at, stop_fn=stop_fn, tick_fn=wait_tick_fn):
            return False
        log_fn("  - Đến giờ đăng")

    if dry_run:
        log_fn(f"  - DRY RUN: {task.video_path.name}")
        return True

    if _should_stop(stop_fn):
        return False

    def on_navigation_retry(next_attempt: int, error_class: str, delay: float) -> None:
        log_fn(
            f"  - [RETRY] Lỗi mạng tạm thời trước submit; thử {next_attempt}/"
            f"{(retry_policy or RetryPolicy()).max_attempts} sau {delay:.2f}s"
        )
        if event_logger:
            event_logger.emit(
                "retry_scheduled",
                row_number=task.row_number,
                status="retrying",
                attempt=next_attempt,
                error_class=error_class,
                delay_ms=round(delay * 1000),
            )

    run_with_bounded_retry(
        lambda: page.goto(task.group_url, wait_until="domcontentloaded"),
        policy=retry_policy,
        stop_fn=stop_fn,
        on_retry=on_navigation_retry,
    )
    dismiss_common_popups(page)
    open_composer(page)
    if target_is_personal and mode != AUDIENCE_DEFAULT:
        set_personal_audience(page, mode)
    upload_video(page, task.video_path)
    fill_caption(page, task.caption)
    click_post(page)
    wait_post_done(page, post_timeout_ms)
    log_fn("  - [OK] Đã gửi bài")
    return True


def run_tasks(
    tasks: list[PostTask],
    config: RunnerConfig,
    *,
    dry_run: bool = False,
    log_fn: LogFn | None = None,
    stop_fn: StopFn | None = None,
    wait_tick_fn: TickFn | None = None,
) -> RunnerStats:
    logger = log_fn or _default_log
    stats = RunnerStats(total=len(tasks))
    retry_policy = RetryPolicy()
    event_logger = JsonlEventLogger(config.event_log_path or default_event_log_path())
    run_started = time.monotonic()
    event_logger.emit(
        "run_started",
        status="running",
        total_tasks=len(tasks),
        dry_run=dry_run,
    )

    if config.max_delay < config.min_delay:
        config.max_delay = config.min_delay

    if not tasks:
        logger("[!] Không có task hợp lệ để chạy")
        event_logger.emit("run_finished", status="empty", total_tasks=0, elapsed_ms=0)
        return stats

    if config.headless and not config.session_path.exists():
        if config.user_data_dir is None:
            event_logger.emit("run_failed", status="failed", error_class="missing_session")
            raise RuntimeError(
                "Headless cần session đăng nhập sẵn. Hãy chạy 1 lần không headless để login."
            )

    logger(f"[i] Tổng task hợp lệ: {len(tasks)}")

    with sync_playwright() as playwright:
        try:
            browser, context = _open_browser_context(playwright, config, log_fn=logger)
        except Exception as error:
            event_logger.emit(
                "run_failed",
                status="failed",
                error_class=classify_retry_error(error),
            )
            if config.user_data_dir is not None:
                raise RuntimeError(
                    "Không mở được browser từ cấu hình Cốc Cốc (profile thật và cả fallback session). "
                    "Hãy tắt hết Cốc Cốc, chạy lại, hoặc tắt tùy chọn 'Dùng Cốc Cốc profile thật'. "
                    f"Chi tiết: {error}"
                ) from error
            raise

        page = context.pages[0] if context.pages else context.new_page()

        try:
            ensure_logged_in(
                page,
                context,
                config.session_path,
                log_fn=logger,
                interactive_login=config.interactive_login,
                login_wait_timeout_seconds=config.login_wait_timeout_seconds,
                stop_fn=stop_fn,
            )

            for index, task in enumerate(tasks, start=1):
                if _should_stop(stop_fn):
                    stats.stopped = True
                    logger("[!] Đã dừng theo yêu cầu người dùng")
                    event_logger.emit(
                        "run_stopped",
                        status="stopped",
                        completed_tasks=stats.success + stats.failed,
                    )
                    break

                task_started = time.monotonic()
                event_logger.emit(
                    "task_started",
                    row_number=task.row_number,
                    status="running",
                    queue_index=index,
                )
                try:
                    completed = post_video_to_group(
                        page,
                        task,
                        post_timeout_ms=config.post_timeout_ms,
                        dry_run=dry_run,
                        stop_fn=stop_fn,
                        wait_tick_fn=wait_tick_fn,
                        log_fn=logger,
                        event_logger=event_logger,
                        retry_policy=retry_policy,
                    )
                    if not completed:
                        stats.stopped = True
                        logger("[!] Đã dừng theo yêu cầu người dùng")
                        event_logger.emit(
                            "task_finished",
                            row_number=task.row_number,
                            status="stopped",
                            elapsed_ms=round((time.monotonic() - task_started) * 1000),
                        )
                        break
                    stats.success += 1
                    event_logger.emit(
                        "task_finished",
                        row_number=task.row_number,
                        status="success",
                        elapsed_ms=round((time.monotonic() - task_started) * 1000),
                    )
                except Exception as post_error:
                    stats.failed += 1
                    screenshot = error_artifact_path(task.row_number)
                    try:
                        screenshot.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(screenshot), full_page=True)
                        logger("  - Ảnh lỗi đã lưu trong thư mục dữ liệu cục bộ.")
                    except Exception:
                        logger("  - Không lưu được ảnh lỗi cục bộ.")
                    error_class = classify_retry_error(post_error)
                    logger(f"  - [ERR] {post_error}")
                    event_logger.emit(
                        "task_finished",
                        row_number=task.row_number,
                        status="failed",
                        error_class=error_class,
                        elapsed_ms=round((time.monotonic() - task_started) * 1000),
                    )

                if index < len(tasks) and not stats.stopped:
                    sleep_seconds = random.randint(config.min_delay, config.max_delay)
                    logger(f"  - Nghỉ {sleep_seconds}s trước bài tiếp theo")
                    for remaining in range(sleep_seconds, 0, -1):
                        if _should_stop(stop_fn):
                            stats.stopped = True
                            logger("[!] Đã dừng theo yêu cầu người dùng")
                            break
                        if wait_tick_fn:
                            wait_tick_fn(remaining)
                        time.sleep(1)

                    if stats.stopped:
                        break

            save_session_state(context, config.session_path)
            logger("\n[OK] Hoàn tất. Session cục bộ đã được cập nhật an toàn.")
            logger(
                f"[i] Kết quả: thành công={stats.success}, lỗi={stats.failed}, dừng={stats.stopped}"
            )
            event_logger.emit(
                "run_finished",
                status="stopped" if stats.stopped else "finished",
                success=stats.success,
                failed=stats.failed,
                stopped=stats.stopped,
                elapsed_ms=round((time.monotonic() - run_started) * 1000),
            )
        finally:
            context.close()
            if browser is not None:
                browser.close()

    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto đăng video vào nhóm Facebook từ file CSV"
    )
    parser.add_argument(
        "--csv",
        default="posts.csv",
        help="Đường dẫn file CSV danh sách bài đăng (mặc định: posts.csv)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Chạy browser ẩn (mặc định hiện browser)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ đọc lịch và dữ liệu, không thực hiện đăng",
    )
    parser.add_argument(
        "--browser-executable-path",
        default="",
        help="Đường dẫn browser.exe (ví dụ Cốc Cốc)",
    )
    parser.add_argument(
        "--browser-user-data-dir",
        default="",
        help="User Data dir để mở profile thật",
    )
    parser.add_argument(
        "--browser-profile-directory",
        default="",
        help="Tên thư mục profile, ví dụ: Profile 4",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    csv_path = Path(args.csv).resolve()
    config = build_config_from_env(headless_override=args.headless)

    if args.browser_executable_path.strip():
        config.browser_executable_path = args.browser_executable_path.strip()
    if args.browser_user_data_dir.strip():
        config.user_data_dir = Path(args.browser_user_data_dir.strip()).expanduser().resolve()
    if args.browser_profile_directory.strip():
        config.profile_directory = args.browser_profile_directory.strip()

    try:
        tasks = load_tasks(csv_path)
    except Exception as error:
        print(f"[X] Lỗi dữ liệu: {error}")
        return 1

    def cli_tick(seconds_left: int) -> None:
        mins, secs = divmod(max(seconds_left, 0), 60)
        print(f"  - Chờ: còn {mins:02d}:{secs:02d}", end="\r", flush=True)

    try:
        run_tasks(
            tasks,
            config,
            dry_run=args.dry_run,
            wait_tick_fn=cli_tick,
        )
    except (PlaywrightTimeoutError, TimeoutError) as error:
        print(f"[X] Timeout: {error}")
        return 1
    except KeyboardInterrupt:
        print("\n[!] Đã dừng bởi người dùng")
        return 130
    except Exception as error:
        print(f"[X] Lỗi runtime: {error}")
        return 1

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
