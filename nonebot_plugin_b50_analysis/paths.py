from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PACKAGE_ASSETS_DIR = BASE_DIR / "assets"
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = PACKAGE_ASSETS_DIR
FONT_CN = PACKAGE_ASSETS_DIR / "ui" / "fonts" / "SourceHanSansSC-Bold.otf"
FONT_EN = PACKAGE_ASSETS_DIR / "ui" / "fonts" / "Torus SemiBold.otf"
