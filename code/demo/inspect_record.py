#!/usr/bin/env python3
"""Inspect a copyright-safe MS3 example record using the standard library."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_TOP_LEVEL = {"record_type", "paper", "ms3_terms", "evidence", "mechanisms"}
LAYERS = ("material", "sensor", "signal", "system")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    args = parser.parse_args()

    record = json.loads(args.record.read_text(encoding="utf-8"))
    missing = REQUIRED_TOP_LEVEL - set(record)
    if missing:
        raise SystemExit(f"Missing top-level fields: {sorted(missing)}")

    evidence_ids = {item["evidence_id"] for item in record["evidence"]}
    print(f"paper_id: {record['paper']['paper_id']}")
    for mechanism in record["mechanisms"]:
        path = mechanism["path"]
        ordered = " -> ".join(path.get(layer) or "[missing]" for layer in LAYERS)
        dangling = sorted(set(mechanism["evidence_chain"]) - evidence_ids)
        print(f"{mechanism['mechanism_id']}: {ordered}")
        print("  supported relations:", ", ".join(mechanism["supported_relations"]))
        print("  evidence chain:", ", ".join(mechanism["evidence_chain"]))
        if dangling:
            raise SystemExit(f"Unknown evidence identifiers: {dangling}")
    print("validation: PASS")


if __name__ == "__main__":
    main()
