#!/usr/bin/env python3
"""Regenerate the release manifest after an intentional versioned update."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("release_root", nargs="?", type=Path, default=Path("."))
    args = parser.parse_args()
    root = args.release_root.resolve()
    output = root / "manifests/MANIFEST.tsv"
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.resolve() != output.resolve()
        and ".git" not in path.relative_to(root).parts
        and path.name != ".DS_Store"
        and not path.name.startswith("._")
        and "__pycache__" not in path.relative_to(root).parts
        and path.suffix != ".pyc"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("relative_path", "bytes", "sha256"))
        for path in files:
            writer.writerow((path.relative_to(root).as_posix(), path.stat().st_size, sha256(path)))
    print(f"wrote {len(files)} entries to {output}")


if __name__ == "__main__":
    main()
