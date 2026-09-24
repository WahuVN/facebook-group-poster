# Facebook Publishing Assistant

A local Windows desktop tool for planning and publishing posts to Facebook destinations that you control or are authorized to use. It combines a **Tkinter GUI** with a **Playwright** automation engine and a scriptable CLI.

## What it demonstrates

- Desktop workflow design with GUI + CLI entry points.
- Browser automation through Playwright with persistent or temporary sessions.
- CSV-driven task loading and validation.
- Scheduled queues, per-task audience settings, dry-run mode, stop controls and progress logging.
- Import/export workflows for destination lists and post plans.
- Structured redacted JSONL diagnostics, local error artifacts and atomic session persistence.
- Pure helper logic covered by unit tests and Windows CI.

## Responsible use

Use this project only with accounts, pages, profiles and groups where you have permission to publish. Facebook can change its UI and automation rules at any time; review the applicable platform terms and rate limits before use.

The default workflow includes delays between tasks and a **Dry Run** mode so a queue can be validated without publishing. Transient network failures are retried with bounded exponential backoff only before submit; ambiguous post-submit state is never retried automatically, preventing accidental duplicate publishing.

## Requirements

- Windows 10/11
- Python 3.10+
- A supported Chromium-based browser or Playwright Chromium

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Run the GUI

```powershell
python fb_group_poster_gui.py
```

Or double-click `Start_FB_Tool.bat`.

## CLI

```powershell
python fb_group_poster.py --csv posts.csv --dry-run
```

Start from `posts.sample.csv`. Supported fields include `enabled`, `group_url`, `video_path`, `caption`, `schedule_at`, and `audience`.

Accepted schedule formats include `YYYY-MM-DD HH:MM`, `DD/MM/YYYY HH:MM`, and variants with seconds.

## Browser/session options

Configuration can be supplied through `.env` (copy `.env.example`) or the GUI. By default, session state is stored outside the repository at `%LOCALAPPDATA%\WAHU\FacebookPublisher\session.json`; structured logs go to `logs\events.jsonl` and error screenshots to `artifacts\`. Repository ignore rules also cover local overrides.

Useful settings include:

- `HEADLESS`
- `FB_SESSION_PATH` (optional override; blank uses the LocalAppData default)
- `FB_EVENT_LOG_PATH` (optional override; blank uses the LocalAppData default)
- `FB_LOCALE` / `FB_TIMEZONE`
- `MIN_DELAY_SECONDS` / `MAX_DELAY_SECONDS`
- `POST_TIMEOUT_MS`
- `BROWSER_EXECUTABLE_PATH`
- `BROWSER_USER_DATA_DIR`
- `BROWSER_PROFILE_DIRECTORY`

## Tests

```powershell
python -m unittest discover -s tests -v
python -m compileall -q fb_group_poster.py fb_group_poster_gui.py tests
```

## Architecture

```text
fb_group_poster.py       Core task model, CSV validation and Playwright runner
fb_group_poster_gui.py   Tkinter desktop workflow
posts.sample.csv         Example queue input
.env.example             Safe configuration template
tests/                   Pure helper/validation tests
.github/workflows/       Windows CI
```

Authentication remains local to the browser/session you choose. Do not commit session state, cookies, `.env` files, or browser profile data.

---

Vietnamese note: đây là công cụ hỗ trợ lên lịch và đăng nội dung bằng browser automation cho các tài khoản/nhóm mà bạn có quyền sử dụng; có GUI, CLI và chế độ Dry Run.