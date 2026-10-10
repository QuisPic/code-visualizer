"""Download the tree-sitter grammars codeviz uses into a folder that the desktop app bundles.

    python packaging/fetch_grammars.py build/grammars

The packaged app points tree-sitter-language-pack at this folder (see `codeviz.desktop.app`), so it
works offline and never downloads at run time.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import tree_sitter_language_pack as tslp

from codeviz.languages import BY_EXTENSION


def main() -> int:
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "build/grammars").resolve()
    shutil.rmtree(dest, ignore_errors=True)
    tslp.configure(tslp.PackConfig(cache_dir=str(dest)))
    names = sorted({lang.name for lang in BY_EXTENSION.values()})
    tslp.download(names)
    missing = set(names) - set(tslp.downloaded_languages())
    if missing:
        print(f"error: grammars missing after download: {sorted(missing)}", file=sys.stderr)
        return 1
    for version in dest.glob("*/v*"):
        shutil.rmtree(version / "bundles", ignore_errors=True)  # the downloaded archive, already unpacked
        (version / ".download.lock").touch()  # so a read-only install doesn't need to create it
    size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
    print(f"{len(names)} grammars, {size / 1e6:.1f} MB in {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
