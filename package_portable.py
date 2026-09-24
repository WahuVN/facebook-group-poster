from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
PRODUCT = "FacebookPublisher"
ARCHIVE_NAME = "FacebookPublisher-NOT_PUBLIC_RELEASE-windows-x64.zip"
SOURCE_DATE_EPOCH = 315532800
LOCKED_RUNTIME = {
    "greenlet": "3.5.0",
    "playwright": "1.54.0",
    "pyee": "13.0.1",
    "python-dotenv": "1.1.1",
    "typing_extensions": "4.15.0",
    "windnd": "1.0.7",
}
LOCKED_BUILD = {"PyInstaller": "6.22.2"}
SOURCE_INPUTS = (
    ".env.example",
    "Build_Internal_Portable.bat",
    "FacebookPublisher.spec",
    "NOT_PUBLIC_RELEASE.txt",
    "PORTABLE_PACKAGING.md",
    "README.md",
    "fb_group_poster.py",
    "fb_group_poster_gui.py",
    "package_portable.py",
    "portable_launcher.py",
    "portable_preflight.py",
    "posts.sample.csv",
    "requirements-build.lock",
    "requirements-runtime.lock",
    "Start_FB_Tool.bat",
    "Setup_FB_Tool.bat",
    "tests/test_packaging.py",
)
FORBIDDEN_PACKAGE_NAMES = {
    ".env", ".env.local", ".fb_session.json", "session.json", "posts.csv", "events.jsonl",
}
FORBIDDEN_PREFIXES = ("error_", "events-")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _dist_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def validate_locked_environment() -> list[str]:
    errors: list[str] = []
    for name, expected in {**LOCKED_RUNTIME, **LOCKED_BUILD}.items():
        actual = _dist_version(name)
        if actual != expected:
            errors.append(f"{name}: expected {expected}, got {actual or 'missing'}")
    return errors


def public_release_allowed() -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if not (ROOT / "LICENSE").is_file():
        blockers.append("root LICENSE chưa tồn tại")
    if not (ROOT / "PUBLIC_RELEASE_AUTHORITY.json").is_file():
        blockers.append("chưa có owner/controller public-release authority")
    return (not blockers, blockers)


def is_forbidden_relative(path: Path) -> bool:
    lowered_parts = [part.lower() for part in path.parts]
    name = path.name.lower()
    if any(part in {".venv", "venv", "__pycache__", "ms-playwright", ".playwright"} for part in lowered_parts):
        return True
    if name in FORBIDDEN_PACKAGE_NAMES:
        return True
    if name.endswith((".pyc", ".pyo", ".sqlite", ".db", ".log")):
        return True
    if name.startswith(FORBIDDEN_PREFIXES):
        return True
    return False


def source_hashes() -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in SOURCE_INPUTS:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Missing canonical packaging input: {relative}")
        result[relative] = sha256_file(path)
    return dict(sorted(result.items()))


def third_party_metadata() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for dist_name in LOCKED_RUNTIME:
        metadata = importlib.metadata.metadata(dist_name)
        rows.append({
            "name": metadata.get("Name") or dist_name,
            "version": importlib.metadata.version(dist_name),
            "license": metadata.get("License-Expression") or metadata.get("License") or "UNDECLARED_METADATA",
            "homepage": metadata.get("Home-page") or "",
        })
    return sorted(rows, key=lambda row: row["name"].lower())


def deterministic_zip(source_dir: Path, output_zip: Path) -> None:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    temp_zip = output_zip.with_name(output_zip.name + ".tmp")
    if temp_zip.exists():
        temp_zip.unlink()
    paths = sorted(
        (item for item in source_dir.rglob("*") if item.is_file()),
        key=lambda p: p.relative_to(source_dir).as_posix(),
    )
    with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as archive:
        for path in paths:
            relative = path.relative_to(source_dir)
            if is_forbidden_relative(relative):
                raise RuntimeError(f"Forbidden runtime/local-state path entered package: {relative.as_posix()}")
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.flag_bits |= 0x800
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    os.replace(temp_zip, output_zip)


def write_internal_checksums(staging: Path) -> None:
    lines: list[str] = []
    paths = sorted(
        (item for item in staging.rglob("*") if item.is_file()),
        key=lambda p: p.relative_to(staging).as_posix(),
    )
    for path in paths:
        relative = path.relative_to(staging)
        if relative.name == "SHA256SUMS.txt":
            continue
        if is_forbidden_relative(relative):
            raise RuntimeError(f"Forbidden path in staging: {relative.as_posix()}")
        lines.append(f"{sha256_file(path)}  {relative.as_posix()}")
    (staging / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, check=True, text=True, capture_output=True, timeout=timeout)


def _git_state() -> dict[str, Any]:
    try:
        head = _run(["git", "rev-parse", "HEAD"], timeout=30).stdout.strip()
        status = _run(["git", "status", "--porcelain"], timeout=30).stdout.splitlines()
        return {"head": head, "dirty": bool(status)}
    except Exception:
        return {"head": "", "dirty": True}


def _build_timestamp() -> str:
    return datetime.fromtimestamp(SOURCE_DATE_EPOCH, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def build_manifest(staging: Path) -> dict[str, Any]:
    public_ok, public_blockers = public_release_allowed()
    payload = {
        "schemaVersion": 1,
        "product": PRODUCT,
        "channel": "internal",
        "publicRelease": False,
        "publicReleaseGateSatisfied": public_ok,
        "publicReleaseBlockers": public_blockers,
        "notPublicRelease": True,
        "sourceDateEpoch": SOURCE_DATE_EPOCH,
        "builtAtUtc": _build_timestamp(),
        "source": {**_git_state(), "files": source_hashes()},
        "buildEnvironment": {
            "python": ".".join(map(str, sys.version_info[:3])),
            "pyinstaller": _dist_version("PyInstaller"),
            "platform": sys.platform,
        },
        "dependencyLocks": {
            "runtimeLockSha256": sha256_file(ROOT / "requirements-runtime.lock"),
            "buildLockSha256": sha256_file(ROOT / "requirements-build.lock"),
            "runtime": LOCKED_RUNTIME,
            "build": LOCKED_BUILD,
        },
        "browserRuntime": {
            "bundled": False,
            "reason": "Browser binary is external to this package; configure an installed Chromium-based browser or a Playwright cache.",
        },
        "thirdPartyMetadata": third_party_metadata(),
    }
    (staging / "BUILD_MANIFEST.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return payload


def smoke_test(executable: Path, report_path: Path) -> dict[str, Any]:
    if report_path.exists():
        report_path.unlink()
    completed = subprocess.run(
        [str(executable), "--preflight", "--preflight-output", str(report_path)],
        cwd=executable.parent,
        check=False,
        timeout=45,
    )
    if completed.returncode not in (0, 2):
        raise RuntimeError(f"Portable smoke returned unexpected exit code {completed.returncode}")
    if not report_path.is_file():
        raise RuntimeError("Portable smoke did not write preflight report")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("ok"):
        raise RuntimeError("Portable preflight has fatal failures: " + "; ".join(report.get("fatal", [])))
    return report


def build(output_root: Path) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    env_errors = validate_locked_environment()
    if env_errors:
        raise RuntimeError("Build environment lock mismatch: " + "; ".join(env_errors))

    work_root = output_root / "_work"
    dist_root = work_root / "dist"
    pyinstaller_work = work_root / "pyinstaller"
    if work_root.exists():
        shutil.rmtree(work_root)
    dist_root.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["SOURCE_DATE_EPOCH"] = str(SOURCE_DATE_EPOCH)
    env["PYTHONHASHSEED"] = "0"
    env["TZ"] = "UTC"

    _run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(dist_root), "--workpath", str(pyinstaller_work),
        str(ROOT / "FacebookPublisher.spec"),
    ], env=env, timeout=900)

    staging = dist_root / PRODUCT
    executable = staging / f"{PRODUCT}.exe"
    if not executable.is_file():
        raise RuntimeError(f"PyInstaller output missing: {executable}")

    manifest = build_manifest(staging)
    write_internal_checksums(staging)
    smoke_path = output_root / "portable-smoke.json"
    smoke = smoke_test(executable, smoke_path)

    archive = output_root / ARCHIVE_NAME
    deterministic_zip(staging, archive)
    archive_hash = sha256_file(archive)
    (output_root / f"{ARCHIVE_NAME}.sha256").write_text(
        f"{archive_hash}  {ARCHIVE_NAME}\n", encoding="utf-8", newline="\n"
    )
    (output_root / "BUILD_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n"
    )
    shutil.rmtree(work_root, ignore_errors=True)

    return {
        "artifact": str(archive),
        "artifactSha256": archive_hash,
        "artifactSize": archive.stat().st_size,
        "smoke": smoke,
        "manifest": str(output_root / "BUILD_MANIFEST.json"),
        "checksum": str(output_root / f"{ARCHIVE_NAME}.sha256"),
        "publicRelease": False,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic internal Windows portable package.")
    parser.add_argument("--output", type=Path, default=ROOT / "dist_internal")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = build(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
