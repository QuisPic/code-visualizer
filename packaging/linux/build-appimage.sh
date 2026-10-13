#!/bin/sh
# Wrap the PyInstaller build (dist/codeviz/) into dist/codeviz-<name>.AppImage and dist/codeviz-<name>.tar.gz.
#     packaging/linux/build-appimage.sh linux-x64
set -eu
NAME="${1:-linux-x64}"
HERE="$(dirname "$(readlink -f "$0")")"
APPDIR=build/codeviz.AppDir

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib"
cp -a dist/codeviz "$APPDIR/usr/lib/codeviz"
cp "$HERE/AppRun" "$HERE/codeviz.desktop" "$APPDIR/"
cp "$HERE/../icon.png" "$APPDIR/codeviz.png"

TOOL=build/appimagetool
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi
# --appimage-extract-and-run: CI machines and containers often have no FUSE
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "dist/codeviz-$NAME.AppImage"
tar -czf "dist/codeviz-$NAME.tar.gz" -C dist codeviz
