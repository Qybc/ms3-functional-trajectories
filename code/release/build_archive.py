#!/usr/bin/env python3
"""Create a deterministic ZIP archive of the validated MS3 release."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


FIXED_TIME = (2026, 9, 18, 0, 0, 0)
EXCLUDED_NAMES = {".DS_Store"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("release_root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("output_zip", type=Path)
    parser.add_argument(
        "--top-level-name",
        help="directory name used inside the ZIP (defaults to the release directory name)",
    )
    args = parser.parse_args()

    root = args.release_root.resolve()
    output = args.output_zip.resolve()
    if output == root or root in output.parents:
        raise SystemExit("output ZIP must be outside the release directory")

    files = sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and path.name not in EXCLUDED_NAMES
        and not path.name.startswith("._")
        and ".git" not in path.relative_to(root).parts
        and "__pycache__" not in path.relative_to(root).parts
        and path.suffix != ".pyc"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    top = args.top_level_name or root.name
    if not top or "/" in top or "\\" in top or top in {".", ".."}:
        raise SystemExit("invalid --top-level-name")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(f"{top}/{relative}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o644 & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED,
                             compresslevel=9)
    print(f"wrote {len(files)} files to {output}")


if __name__ == "__main__":
    main()
