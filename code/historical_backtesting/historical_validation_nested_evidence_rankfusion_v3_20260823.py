#!/usr/bin/env python3
"""Exploratory leakage-safe rank fusion for MS3 evidence reranking.

This protocol replaces raw-score addition with calibration-robust percentile
rank fusion.  Selection uses four completed four-year development horizons
for each outer cutoff and rewards both validated-closure head utility and
popularity-matched discrimination.  The 2018--2021 windows have been examined
in prior experiments, so this run is model development, not a fresh
confirmatory evaluation.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import historical_validation_nested_evidence_popularity_v1_20260823 as base


RANK_FUSION_MODES = (
    "global_percentile_blend",
    "structure_gated_percentile_blend",
    "head_taper_percentile_blend_40",
    "head_taper_percentile_blend_80",
)
RANK_WEIGHT_GRID = (0.025, 0.05, 0.10, 0.15, 0.20, 0.30)


def completed_development_cutoffs(outer: int) -> tuple[int, ...]:
    last = outer - 4
    return tuple(range(last - 3, last + 1))


def percentile_map(rows, key):
    ordered = sorted(rows, key=lambda row: (float(row[key]), row["trajectory"]))
    denominator = max(1, len(ordered) - 1)
    return {
        row["trajectory"]: index / denominator
        for index, row in enumerate(ordered)
    }


def rank_fusion_scores(rows, composite: str, weight: float, mode: str):
    evidence_key = f"score_independent_{composite}"
    structure = percentile_map(rows, "score_structure_only")
    evidence = percentile_map(rows, evidence_key)
    scores = {}
    for row in rows:
        trajectory = row["trajectory"]
        structural_rank = structure[trajectory]
        evidence_rank = evidence[trajectory]
        centered_evidence = evidence_rank - 0.5
        if mode == "global_percentile_blend":
            gate = 1.0
        elif mode == "structure_gated_percentile_blend":
            gate = 0.25 + 0.75 * structural_rank
        elif mode.startswith("head_taper_percentile_blend_"):
            width = float(mode.rsplit("_", 1)[-1])
            # Smoothly concentrate evidence leverage in the reviewable head,
            # without fixing any rank or excluding any candidate from moving.
            descending_rank = len(rows) - int(round(structural_rank * (len(rows) - 1)))
            gate = (0.25 + 0.75 * structural_rank) / (
                1.0 + max(0.0, descending_rank - 200.0) / width
            )
        else:
            raise ValueError(mode)
        scores[trajectory] = structural_rank + weight * centered_evidence * gate
    return scores


def rank_fusion_order(rows, composite: str, weight: float, mode: str):
    scores = rank_fusion_scores(rows, composite, weight, mode)
    ranked = sorted(rows, key=lambda row: (-scores[row["trajectory"]], row["trajectory"]))
    return ranked, scores


def matched_accuracy(pairs, score_map):
    return statistics.mean(
        base.comparison(score_map[pos["trajectory"]], score_map[neg["trajectory"]])
        for pos, neg in pairs
    )


def development_record(
    band, rows_by_cutoff, structure_metrics, matched_pairs, composite, weight, mode,
):
    # Reuse the predeclared multi-budget and strict-safety calculations after
    # replacing only the score-fusion function.
    record = base.configuration_record(
        band, rows_by_cutoff, structure_metrics, composite, weight, mode
    )
    full_acc = []
    role_acc = []
    structure_acc = []
    for cutoff, rows in rows_by_cutoff.items():
        pairs = matched_pairs[cutoff]
        full_scores = rank_fusion_scores(rows, composite, weight, mode)
        role_scores = {
            row["trajectory"]: float(row["score_untyped_cooccurrence"])
            for row in rows
        }
        structure_scores = {
            row["trajectory"]: float(row["score_structure_only"])
            for row in rows
        }
        full_acc.append(matched_accuracy(pairs, full_scores))
        role_acc.append(matched_accuracy(pairs, role_scores))
        structure_acc.append(matched_accuracy(pairs, structure_scores))
    record["validated_matched_accuracy"] = statistics.mean(full_acc)
    record["validated_role_matched_accuracy"] = statistics.mean(role_acc)
    record["validated_structure_matched_accuracy"] = statistics.mean(structure_acc)
    record["validated_matched_delta_vs_role"] = (
        record["validated_matched_accuracy"]
        - record["validated_role_matched_accuracy"]
    )
    record["validated_matched_delta_vs_structure"] = (
        record["validated_matched_accuracy"]
        - record["validated_structure_matched_accuracy"]
    )
    record["selection_score"] = (
        float(record["selection_score"])
        + 0.25 * float(record["validated_matched_delta_vs_role"])
        + 0.25 * float(record["validated_matched_delta_vs_structure"])
    )
    record["eligible"] = bool(record["eligible"]) and (
        float(record["validated_matched_delta_vs_role"]) >= 0
        and float(record["validated_matched_delta_vs_structure"]) >= 0
    )
    return record


def run_select(args) -> None:
    outer = int(args.outer_cutoff)
    output_dir = args.output_root / f"outer_{outer}"
    if output_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing output directory: {output_dir}")
    output_dir.mkdir(parents=True)
    development_cutoffs = completed_development_cutoffs(outer)
    global_model, band, base_model, units, strict_units, audit, reviews, rows_by_cutoff = (
        base.load_feature_rows(args, development_cutoffs, f"rank_select_{outer}")
    )
    structure_metrics = {}
    matched_pairs = {}
    for cutoff, rows in rows_by_cutoff.items():
        structure = base.structure_order(rows)
        for endpoint in base.ENDPOINTS:
            structure_metrics[(cutoff, endpoint)] = band.metrics(structure, endpoint)
        matched_pairs[cutoff] = base.popularity_matched_pairs(
            rows, base.PRIMARY_ENDPOINT
        )

    grid = []
    for composite in base.EVIDENCE_COMPOSITES:
        for mode in RANK_FUSION_MODES:
            for weight in RANK_WEIGHT_GRID:
                grid.append(development_record(
                    band, rows_by_cutoff, structure_metrics, matched_pairs,
                    composite, weight, mode,
                ))
    eligible = [row for row in grid if bool(row["eligible"])]
    selected = sorted(
        eligible or grid,
        key=lambda row: (
            -float(row["selection_score"]),
            int(row["negative_head_cutoff_cells"]),
            -float(row["validated_mean_head_utility_delta"]),
            -float(row["validated_matched_delta_vs_role"]),
            -float(row["validated_mean_delta_ap"]),
            float(row["weight"]),
            str(row["evidence_composite"]),
            str(row["fusion_mode"]),
        ),
    )[0]
    lock = {
        "status": "nested_rank_fusion_outer_model_locked",
        "locked_utc": datetime.now(timezone.utc).isoformat(),
        "outer_cutoff": outer,
        "development_cutoffs": list(development_cutoffs),
        "development_horizons_complete_by_outer": True,
        "outer_outcome_not_loaded": True,
        "analysis_designation": "exploratory_model_development",
        "primary_selection_endpoint": base.PRIMARY_ENDPOINT,
        "strict_closure_safety_constraint": True,
        "popularity_matching_features": [
            "score_untyped_cooccurrence", "score_node_popularity"
        ],
        "selected": selected,
        "predeclared_grid": {
            "evidence_composites": list(base.EVIDENCE_COMPOSITES),
            "fusion_modes": list(RANK_FUSION_MODES),
            "weights": list(RANK_WEIGHT_GRID),
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
    base.evidence_scores = rank_fusion_scores
    base.evidence_order = rank_fusion_order
    if args.phase == "select":
        run_select(args)
    else:
        base.run_evaluate(args)


if __name__ == "__main__":
    main()
