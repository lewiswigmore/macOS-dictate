"""py2app build script for dictate.app

Usage:
    python setup_app.py py2app -A   # alias mode (fast, dev)
    python setup_app.py py2app      # production mode (slow, bundles everything)

The resulting .app appears in dist/dictate.app.

This script is intentionally separate from pyproject.toml so pip installs are
unaffected. py2app is only required for building the .app bundle:

    pip install py2app
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from setuptools import setup
except ImportError:
    sys.exit("setuptools required. pip install setuptools")

VERSION = "0.1.0"
APP = ["dictate/__main__.py"]
DATA_FILES = [
    ("config", [str(p) for p in Path("config").rglob("*") if p.is_file()]),
    ("assets", ["assets/dictate.sdef"] if Path("assets/dictate.sdef").exists() else []),
]

PLIST = {
    "CFBundleName": "dictate",
    "CFBundleDisplayName": "dictate",
    "CFBundleIdentifier": "com.dictate.app",
    "CFBundleShortVersionString": VERSION,
    "CFBundleVersion": VERSION,
    "CFBundleIconFile": "icon.icns",
    "LSMinimumSystemVersion": "13.0",
    "LSUIElement": True,
    "NSMicrophoneUsageDescription": "dictate needs the microphone to transcribe your speech locally.",
    "NSAppleEventsUsageDescription": (
        "dictate uses Apple Events to read selected text in the frontmost app and to handle "
        "dictate:// URL schemes."
    ),
    "NSHumanReadableCopyright": "Copyright (c) 2026 lewiswigmore. MIT License.",
    "CFBundleURLTypes": [
        {
            "CFBundleURLName": "com.dictate.app.URL",
            "CFBundleURLSchemes": ["dictate"],
        }
    ],
    "NSAppleScriptEnabled": True,
    "OSAScriptingDefinition": "dictate.sdef",
}

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "assets/icon.icns",
    "plist": PLIST,
    "packages": ["dictate"],
    "includes": ["pkg_resources"],
    "excludes": [
        "tkinter",
        "matplotlib",
        "scipy.signal",
    ],
}

setup(
    app=APP,
    name="dictate",
    version=VERSION,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
