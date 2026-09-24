from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path.cwd().resolve()
pw_datas, pw_binaries, pw_hiddenimports = collect_all("playwright")

datas = pw_datas + [
    (str(ROOT / ".env.example"), "."),
    (str(ROOT / "posts.sample.csv"), "."),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "PORTABLE_PACKAGING.md"), "."),
    (str(ROOT / "NOT_PUBLIC_RELEASE.txt"), "."),
]

a = Analysis(
    [str(ROOT / "portable_launcher.py")],
    pathex=[str(ROOT)],
    binaries=pw_binaries,
    datas=datas,
    hiddenimports=pw_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FacebookPublisher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FacebookPublisher",
)
