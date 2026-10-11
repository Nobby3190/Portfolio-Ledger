# PyInstaller spec for "帳本 Ledger.app" — build with `./scripts/build_app.sh`.
# -*- mode: python ; coding: utf-8 -*-
import os
import tomllib

with open("pyproject.toml", "rb") as f:
    VERSION = tomllib.load(f)["project"]["version"]

ICON = "packaging/Ledger.icns"

a = Analysis(
    ["packaging/launcher.py"],
    pathex=["src"],
    # app.py loads the frontend from Path(__file__).parent / "ui" and db.py the SQL migrations; keep both next to the package.
    datas=[
        ("src/portfolio_ledger/ui", "portfolio_ledger/ui"),
        ("src/portfolio_ledger/migrations", "portfolio_ledger/migrations"),
    ],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Ledger",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Ledger")

app = BUNDLE(
    coll,
    name="帳本 Ledger.app",
    icon=ICON if os.path.exists(ICON) else None,
    bundle_identifier="com.nobbyhsieh.ledger",
    version=VERSION,
    info_plist={
        "CFBundleName": "Ledger",
        "CFBundleDisplayName": "帳本 Ledger",
        "CFBundleShortVersionString": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "13.0",
    },
)
