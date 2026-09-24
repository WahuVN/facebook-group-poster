from __future__ import annotations

import argparse
import json
from pathlib import Path

from portable_preflight import build_report, write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--preflight", action="store_true", help="Chạy kiểm tra runtime rồi thoát, không mở GUI.")
    parser.add_argument(
        "--preflight-output",
        type=Path,
        default=None,
        help="Ghi báo cáo preflight JSON để smoke test đọc được cả khi EXE chạy windowed.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report()

    if args.preflight_output is not None:
        write_report(args.preflight_output, report)

    if args.preflight:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["ok"] else 2

    if report["fatal"]:
        from tkinter import messagebox
        messagebox.showerror(
            "Facebook Publisher - kiểm tra môi trường",
            "Không thể khởi động:\n\n" + "\n".join(f"- {item}" for item in report["fatal"]),
        )
        return 2

    from fb_group_poster_gui import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
