# PyInstaller spec for the codeviz desktop app.  Run from the repo root after fetch_grammars.py:
#     pyinstaller packaging/codeviz.spec --noconfirm
# Output: dist/codeviz/ (Windows, Linux) or dist/codeviz.app (macOS). On Linux the window is pywebview's Qt
# backend, so install PyQt6 and PyQt6-WebEngine first (the `desktop` extra does that on Linux).
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
VERSION = "0.1.0"
LINUX = sys.platform.startswith("linux")

datas = collect_data_files("codeviz") + [(str(ROOT / "build" / "grammars"), "grammars")]
binaries = collect_dynamic_libs("tree_sitter_language_pack") + collect_dynamic_libs("tree_sitter")

a = Analysis(
    [str(ROOT / "packaging" / "codeviz_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["tree_sitter_language_pack._native"] + (["webview.platforms.qt"] if LINUX else []),
    excludes=["tkinter", "PyQt5", "PySide2", "PySide6", "gi"] + ([] if LINUX else ["PyQt6"]),
)
if LINUX:
    # PyQt6's hooks collect Qt modules the web view never loads (Quick 3D, Quick Controls, multimedia, PDF, ...),
    # QML files and the GTK theme plugin, which drags in the build machine's GTK. Leaving them out saves ~90 MB.
    unused = re.compile(
        r"PyQt6/Qt6/(qml/|plugins/platformthemes/libqgtk3|translations/[^/]*\.qm$|lib/libQt6(Quick3D|QuickControls2"
        r"|QuickDialogs2|QuickTemplates2|QuickTest|QuickTimeline|QuickVectorImage|QuickParticles|QuickEffects"
        r"|QuickShapes|QuickLayouts|Multimedia|Pdf|PositioningQuick|RemoteObjects|Sensors|SerialPort|ShaderTools"
        r"|SpatialAudio|StateMachine|Test|TextToSpeech|WebChannelQuick|WebEngineQuick|WebSockets)"
        r"|plugins/imageformats/libqpdf|plugins/position/libqtposition_nmea)"
        r"|lib(gtk-3|gdk-3|gdk_pixbuf-2\.0|atk-1\.0|atk-bridge-2\.0|atspi|cairo-gobject|epoxy)\.so")
    a.binaries = [b for b in a.binaries if not unused.match(b[0])]
    a.datas = [d for d in a.datas if not unused.match(d[0])]
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
