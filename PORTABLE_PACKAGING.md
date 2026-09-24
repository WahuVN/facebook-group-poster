# Facebook Publishing Assistant — deterministic portable packaging

## Scope

This repository has a canonical **internal Windows portable** lane. It is deliberately
marked `NOT_PUBLIC_RELEASE` while the root LICENSE / redistribution authority remains
unresolved.

The packaging lane does not change the reviewed publishing engine. It preserves dry-run,
queue/cancel, selector diagnostics, redacted logging, and LocalAppData session/log storage.

## Runtime contract

- Runtime dependencies are exact-pinned in `requirements-runtime.lock`.
- `Setup_FB_Tool.bat` is the explicit one-time source setup step.
- `Start_FB_Tool.bat` never upgrades pip, installs packages, or downloads a browser.
- Browser binaries are **not bundled**. Use an installed Chromium-based browser via the
  existing browser settings / `BROWSER_EXECUTABLE_PATH`, or explicitly install the
  Playwright Chromium revision with `Setup_FB_Tool.bat --with-playwright-browser`.
- Session state, event logs, screenshots, posts.csv, browser caches, virtualenvs, and
  bytecode are excluded from the package.

## Build contract

1. Run `Setup_FB_Tool.bat`.
2. Install exact build tools from `requirements-build.lock` (the build BAT does this
   explicitly; the user launcher does not).
3. Run `Build_Internal_Portable.bat [output-directory]`.
4. `package_portable.py` validates exact runtime/build versions, builds the windowed
   PyInstaller one-dir payload with UPX disabled, writes a fixed-epoch manifest,
   writes payload SHA256 sums, runs packaged preflight smoke, and creates a sorted ZIP
   with normalized timestamps.
5. Output filename is always
   `FacebookPublisher-NOT_PUBLIC_RELEASE-windows-x64.zip` plus a matching SHA256 file.

The manifest records current Git HEAD/dirty state and SHA256 for every canonical source
input so an internal package can be traced to exact bytes even before the reviewed source
delta is committed.

## Public-release guard

AI19 intentionally does not provide a public packaging mode. The manifest reports the
missing root LICENSE and owner/controller authority as release blockers. A later release
owner must resolve those gates, review exact third-party notices/provenance, rerun all
tests/smoke/secret checks on current bytes, and only then create a public release lane.
