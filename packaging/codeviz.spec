# PyInstaller spec for the codeviz desktop app.  Run from the repo root after fetch_grammars.py:
#     pyinstaller packaging/codeviz.spec --noconfirm
# Output: dist/codeviz/ (Windows) or dist/codeviz.app (macOS).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
VERSION = "0.1.0"

datas = collect_data_files("codeviz") + [(str(ROOT / "build" / "grammars"), "grammars")]
binaries = collect_dynamic_libs("tree_sitter_language_pack") + collect_dynamic_libs("tree_sitter")

a = Analysis(
    [str(ROOT / "packaging" / "codeviz_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["tree_sitter_language_pack._native"],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "gi"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="codeviz",
    console=False,
    icon=str(ROOT / "packaging" / "icon.png"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="codeviz")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="codeviz.app",
        icon=str(ROOT / "packaging" / "icon.png"),
        bundle_identifier="io.github.quispic.codeviz",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "codeviz",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
