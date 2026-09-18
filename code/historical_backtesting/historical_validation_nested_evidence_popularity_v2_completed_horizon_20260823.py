#!/usr/bin/env python3
"""Leakage-safe wrapper for nested MS3 evidence evaluation.

For an outer cutoff t, model selection uses four recent development cutoffs
c whose entire four-year outcome horizon is observable at t (c + 4 <= t).
The outer t outcome is not loaded until all four selection locks exist.

The scoring grid and evaluation code are inherited unchanged from v1.  This
wrapper exists as a new immutable protocol version because the v1 development
windows were not outcome-censored relative to their outer cutoffs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import historical_validation_nested_evidence_popularity_v1_20260823 as base


def completed_development_cutoffs(outer: int) -> tuple[int, ...]:
    """Four recent cutoffs with complete four-year follow-up by outer."""
    last = outer - 4
    return tuple(range(last - 3, last + 1))


def run_select(args) -> None:
    outer = int(args.outer_cutoff)
    output_dir = args.output_root / f"outer_{outer}"
    if output_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing output directory: {output_dir}")
    output_dir.mkdir(parents=True)
    development_cutoffs = completed_development_cutoffs(outer)
    global_model, band, base_model, units, strict_units, audit, reviews, rows_by_cutoff = (
        base.load_feature_rows(args, development_cutoffs, f"completed_select_{outer}")
    )
    structure_metrics = {}
    for cutoff, rows in rows_by_cutoff.items():
        ranked = base.structure_order(rows)
        for endpoint in base.ENDPOINTS:
            structure_metrics[(cutoff, endpoint)] = band.metrics(ranked, endpoint)

    grid = []
    for composite in base.EVIDENCE_COMPOSITES:
        for mode in base.FUSION_MODES:
            for weight in base.WEIGHT_GRID:
                grid.append(base.configuration_record(
                    band, rows_by_cutoff, structure_metrics, composite, weight, mode
                ))
    eligible = [row for row in grid if bool(row["eligible"])]
    selected = sorted(
        eligible or grid,
        key=lambda row: (
            -float(row["selection_score"]),
            int(row["negative_head_cutoff_cells"]),
            -float(row["validated_mean_head_utility_delta"]),
            -float(row["validated_mean_delta_ap"]),
            float(row["weight"]),
            str(row["evidence_composite"]),
            str(row["fusion_mode"]),
        ),
    )[0]
    lock = {
        "status": "nested_completed_horizon_outer_model_locked",
        "locked_utc": datetime.now(timezone.utc).isoformat(),
        "outer_cutoff": outer,
        "development_cutoffs": list(development_cutoffs),
        "development_horizons_complete_by_outer": True,
        "outer_outcome_not_loaded": True,
        "primary_selection_endpoint": base.PRIMARY_ENDPOINT,
        "strict_closure_safety_constraint": True,
        "popularity_matching_features": [
            "score_untyped_cooccurrence", "score_node_popularity"
        ],
        "selected": selected,
        "predeclared_grid": {
            "evidence_composites": list(base.EVIDENCE_COMPOSITES),
            "fusion_modes": list(base.FUSION_MODES),
            "weights": list(base.WEIGHT_GRID),
        },
        "corpus_sha256": audit.get("data_json_manifest_sha256"),
        "year_overlay_sha256": base.sha256(args.year_overlay),
        "script_sha256": base.sha256(Path(__file__).resolve()),
        "parent_protocol_sha256": base.sha256(Path(base.__file__).resolve()),
        "strict_units": len(strict_units),
        "all_units": len(units),
        "broad_review_papers_excluded": len(reviews),
    }
    base.write_csv(output_dir / "selection_grid.csv", grid)
    (output_dir / "selection_lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(lock, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    args = base.parse_args()
    if args.phase == "select":
        run_select(args)
    else:
        base.run_evaluate(args)


if __name__ == "__main__":
    main()
