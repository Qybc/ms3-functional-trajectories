#!/usr/bin/env python3
"""Nested temporal and popularity-matched evaluation of MS3 evidence ranking.

The protocol addresses three predeclared questions:

1. Does evidence add value when each outer cutoff is scored with a model
   selected only from earlier rolling-origin windows?
2. Is the gain larger for experimentally validated future closures than for
   occurrence-only strict closures?
3. Does structure plus evidence retain discrimination after matching future
   positives to negatives with similar untyped co-occurrence and node
   popularity?

Selection and evaluation are separate phases.  For outer cutoff t, selection
loads only 2015..t-1.  Evaluation requires four previously written locks and
then loads 2018..2021.  Existing products are never overwritten.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OUTER_CUTOFFS = (2018, 2019, 2020, 2021)
K_VALUES = (20, 50, 100, 200)
ENDPOINTS = ("closed_in_future", "validated_closure")
PRIMARY_ENDPOINT = "validated_closure"
SECONDARY_ENDPOINT = "closed_in_future"

# Frozen before this run.  Each item has a scientific interpretation tied to
# evidence recency, validation, weakest-link support or source independence.
EVIDENCE_COMPOSITES = (
    "temporal_validation_momentum",
    "closure_specific_validation",
    "closure_specific_hybrid",
    "temporal_closure_v10",
    "temporal_closure_v20",
    "temporal_closure_v30",
    "temporal_weaklink_v20",
    "replication_validation",
)
FUSION_MODES = (
    "additive_centered",
    "structure_gated_centered",
    "confidence_taper_centered_20",
    "confidence_taper_centered_40",
    "confidence_taper_centered_80",
)
WEIGHT_GRID = (0.025, 0.05, 0.10, 0.20, 0.30)


def import_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("select", "evaluate"), required=True)
    parser.add_argument("--outer-cutoff", type=int, choices=OUTER_CUTOFFS)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--builder", required=True, type=Path)
    parser.add_argument("--v2-script", required=True, type=Path)
    parser.add_argument("--base-recalibration-script", required=True, type=Path)
    parser.add_argument("--clean-temporal-script", required=True, type=Path)
    parser.add_argument("--band-rerank-script", required=True, type=Path)
    parser.add_argument("--replication-rerank-script", required=True, type=Path)
    parser.add_argument("--global-multibudget-script", required=True, type=Path)
    parser.add_argument("--temporal-wrapper-script", required=True, type=Path)
    parser.add_argument("--closure-specific-script", required=True, type=Path)
    parser.add_argument("--year-overlay", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    for key, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, key, value.resolve())
    if args.phase == "select" and args.outer_cutoff is None:
        parser.error("--outer-cutoff is required for selection")
    return args


def load_feature_rows(
    args: argparse.Namespace, cutoffs: tuple[int, ...], suffix: str,
):
    global_model = import_path(args.global_multibudget_script, f"nested_global_{suffix}")
    temporal = import_path(args.temporal_wrapper_script, f"nested_temporal_{suffix}")
    closure = import_path(args.closure_specific_script, f"nested_closure_{suffix}")
    (
        replication, clean, band, base, v2, units, strict_units, audit,
        reviews, rows_by_cutoff, _composites,
    ) = global_model.load_rows(args, suffix, cutoffs)
    for cutoff, rows in rows_by_cutoff.items():
        temporal.add_temporal_scores(base, v2, rows, units, cutoff)
        closure.add_closure_specific_scores(base, temporal, v2, rows, units, cutoff)
        for composite in EVIDENCE_COMPOSITES:
            key = f"score_independent_{composite}"
            if key not in rows[0]:
                raise KeyError(f"Missing evidence score {key} at cutoff {cutoff}")
    return global_model, band, base, units, strict_units, audit, reviews, rows_by_cutoff


def structure_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (-float(row["score_structure_only"]), row["trajectory"]),
    )


def role_agnostic_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (-float(row["score_untyped_cooccurrence"]), row["trajectory"]),
    )


def evidence_scores(
    rows: list[dict[str, Any]], composite: str, weight: float, mode: str,
) -> dict[str, float]:
    evidence_key = f"score_independent_{composite}"
    structure_ranked = structure_order(rows)
    structure_ranks = {
        row["trajectory"]: index + 1 for index, row in enumerate(structure_ranked)
    }
    scores: dict[str, float] = {}
    for row in rows:
        structure = float(row["score_structure_only"])
        evidence = float(row[evidence_key]) - 0.5
        if mode == "additive_centered":
            gate = 1.0
        elif mode == "structure_gated_centered":
            gate = 0.25 + 0.75 * structure
        elif mode.startswith("confidence_taper_centered_"):
            scale = float(mode.rsplit("_", 1)[-1])
            rank = structure_ranks[row["trajectory"]]
            logit = (rank - 120.0) / scale
            if logit >= 50.0:
                taper = 0.0
            elif logit <= -50.0:
                taper = 1.0
            else:
                taper = 1.0 / (1.0 + math.exp(logit))
            gate = (0.25 + 0.75 * structure) * taper
        else:
            raise ValueError(mode)
        scores[row["trajectory"]] = structure + weight * evidence * gate
    return scores


def evidence_order(
    rows: list[dict[str, Any]], composite: str, weight: float, mode: str,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    scores = evidence_scores(rows, composite, weight, mode)
    ranked = sorted(rows, key=lambda row: (-scores[row["trajectory"]], row["trajectory"]))
    return ranked, scores


def head_utility(metrics: dict[str, Any]) -> float:
    return (
        0.35 * float(metrics["precision_at_20"])
        + 0.30 * float(metrics["precision_at_50"])
        + 0.20 * float(metrics["precision_at_100"])
        + 0.05 * float(metrics["precision_at_200"])
        + 0.10 * float(metrics["average_precision"])
    )


def configuration_record(
    band: Any,
    rows_by_cutoff: dict[int, list[dict[str, Any]]],
    structure_metrics: dict[tuple[int, str], dict[str, Any]],
    composite: str,
    weight: float,
    mode: str,
) -> dict[str, Any]:
    deltas: dict[str, dict[int, list[float]]] = {
        endpoint: {k: [] for k in K_VALUES} for endpoint in ENDPOINTS
    }
    ap_deltas = {endpoint: [] for endpoint in ENDPOINTS}
    utility_deltas = {endpoint: [] for endpoint in ENDPOINTS}
    negative_cells = 0
    for cutoff, rows in rows_by_cutoff.items():
        ranked, _scores = evidence_order(rows, composite, weight, mode)
        for endpoint in ENDPOINTS:
            reference = structure_metrics[(cutoff, endpoint)]
            result = band.metrics(ranked, endpoint)
            for k in K_VALUES:
                value = float(result[f"hits_at_{k}"]) - float(reference[f"hits_at_{k}"])
                deltas[endpoint][k].append(value)
                if k <= 100 and value < 0:
                    negative_cells += 1
            ap_value = float(result["average_precision"]) - float(reference["average_precision"])
            ap_deltas[endpoint].append(ap_value)
            utility_deltas[endpoint].append(head_utility(result) - head_utility(reference))

    record: dict[str, Any] = {
        "evidence_composite": composite,
        "fusion_mode": mode,
        "weight": weight,
        "negative_head_cutoff_cells": negative_cells,
    }
    for endpoint in ENDPOINTS:
        short = "validated" if endpoint == PRIMARY_ENDPOINT else "strict"
        for k in K_VALUES:
            values = deltas[endpoint][k]
            record[f"{short}_mean_delta_hits_at_{k}"] = statistics.mean(values)
            record[f"{short}_nonnegative_cutoffs_at_{k}"] = sum(value >= 0 for value in values)
        record[f"{short}_mean_delta_ap"] = statistics.mean(ap_deltas[endpoint])
        record[f"{short}_mean_head_utility_delta"] = statistics.mean(utility_deltas[endpoint])
        record[f"{short}_sd_head_utility_delta"] = statistics.pstdev(utility_deltas[endpoint])

    # Validated closure is the selection target; strict closure is a safety
    # constraint.  The score rewards validation-specific gain and stability.
    record["selection_score"] = (
        float(record["validated_mean_head_utility_delta"])
        - 0.20 * float(record["validated_sd_head_utility_delta"])
        + 0.20 * float(record["strict_mean_head_utility_delta"])
        - 0.10 * float(record["strict_sd_head_utility_delta"])
        - 0.0004 * negative_cells
    )
    dev_count = len(rows_by_cutoff)
    record["eligible"] = (
        all(float(record[f"validated_mean_delta_hits_at_{k}"]) >= 0 for k in K_VALUES)
        and all(float(record[f"strict_mean_delta_hits_at_{k}"]) >= 0 for k in K_VALUES)
        and float(record["validated_mean_delta_ap"]) >= 0
        and int(record["negative_head_cutoff_cells"]) <= max(2, dev_count)
        and any(float(record[f"validated_mean_delta_hits_at_{k}"]) > 0 for k in (20, 50, 100))
    )
    return record


def run_select(args: argparse.Namespace) -> None:
    outer = int(args.outer_cutoff)
    output_dir = args.output_root / f"outer_{outer}"
    if output_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing output directory: {output_dir}")
    output_dir.mkdir(parents=True)
    development_cutoffs = tuple(range(2015, outer))
    global_model, band, base, units, strict_units, audit, reviews, rows_by_cutoff = (
        load_feature_rows(args, development_cutoffs, f"select_{outer}")
    )
    structure_metrics: dict[tuple[int, str], dict[str, Any]] = {}
    for cutoff, rows in rows_by_cutoff.items():
        ranked = structure_order(rows)
        for endpoint in ENDPOINTS:
            structure_metrics[(cutoff, endpoint)] = band.metrics(ranked, endpoint)

    grid: list[dict[str, Any]] = []
    for composite in EVIDENCE_COMPOSITES:
        for mode in FUSION_MODES:
            for weight in WEIGHT_GRID:
                grid.append(configuration_record(
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
        "status": "nested_outer_model_locked",
        "locked_utc": datetime.now(timezone.utc).isoformat(),
        "outer_cutoff": outer,
        "development_cutoffs": list(development_cutoffs),
        "outer_outcome_not_loaded": True,
        "primary_selection_endpoint": PRIMARY_ENDPOINT,
        "strict_closure_safety_constraint": True,
        "popularity_matching_features": [
            "score_untyped_cooccurrence", "score_node_popularity"
        ],
        "selected": selected,
        "predeclared_grid": {
            "evidence_composites": list(EVIDENCE_COMPOSITES),
            "fusion_modes": list(FUSION_MODES),
            "weights": list(WEIGHT_GRID),
        },
        "corpus_sha256": audit.get("data_json_manifest_sha256"),
        "year_overlay_sha256": sha256(args.year_overlay),
        "script_sha256": sha256(Path(__file__).resolve()),
        "strict_units": len(strict_units),
        "all_units": len(units),
        "broad_review_papers_excluded": len(reviews),
    }
    write_csv(output_dir / "selection_grid.csv", grid)
    (output_dir / "selection_lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(lock, ensure_ascii=False, indent=2), flush=True)


def comparison(left: float, right: float) -> float:
    if left > right:
        return 1.0
    if left < right:
        return 0.0
    return 0.5


def popularity_matched_pairs(
    rows: list[dict[str, Any]], endpoint: str, negatives_per_positive: int = 5,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    positives = [row for row in rows if int(row[endpoint])]
    negatives = [row for row in rows if not int(row[endpoint])]
    bins: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in negatives:
        role_bin = min(19, int(float(row["score_untyped_cooccurrence"]) * 20.0))
        node_bin = min(19, int(float(row["score_node_popularity"]) * 20.0))
        bins[(role_bin, node_bin)].append(row)
    for values in bins.values():
        values.sort(key=lambda row: row["trajectory"])

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for positive in sorted(positives, key=lambda row: row["trajectory"]):
        role = float(positive["score_untyped_cooccurrence"])
        node = float(positive["score_node_popularity"])
        role_bin = min(19, int(role * 20.0))
        node_bin = min(19, int(node * 20.0))
        pool: list[dict[str, Any]] = []
        for radius in range(0, 20):
            for key, values in bins.items():
                if max(abs(key[0] - role_bin), abs(key[1] - node_bin)) == radius:
                    pool.extend(values)
            if len(pool) >= negatives_per_positive:
                break
        pool.sort(key=lambda row: (
            abs(float(row["score_untyped_cooccurrence"]) - role)
            + abs(float(row["score_node_popularity"]) - node),
            row["trajectory"],
        ))
        for negative in pool[:negatives_per_positive]:
            pairs.append((positive, negative))
    return pairs


def run_evaluate(args: argparse.Namespace) -> None:
    output_dir = args.output_root / "nested_evaluation"
    if output_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing evaluation: {output_dir}")
    locks: dict[int, dict[str, Any]] = {}
    for outer in OUTER_CUTOFFS:
        path = args.output_root / f"outer_{outer}" / "selection_lock.json"
        if not path.exists():
            raise SystemExit(f"Missing nested selection lock: {path}")
        lock = json.loads(path.read_text(encoding="utf-8"))
        if int(lock["outer_cutoff"]) != outer:
            raise RuntimeError(f"Lock cutoff mismatch: {path}")
        locks[outer] = lock
    output_dir.mkdir(parents=True)

    global_model, band, base, units, strict_units, audit, reviews, rows_by_cutoff = (
        load_feature_rows(args, OUTER_CUTOFFS, "nested_evaluate")
    )
    for lock in locks.values():
        if lock.get("corpus_sha256") != audit.get("data_json_manifest_sha256"):
            raise RuntimeError("Corpus hash differs from nested selection lock")
        if lock.get("year_overlay_sha256") != sha256(args.year_overlay):
            raise RuntimeError("Year overlay differs from nested selection lock")

    metric_rows: list[dict[str, Any]] = []
    match_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    for cutoff, rows in rows_by_cutoff.items():
        selected = locks[cutoff]["selected"]
        structure = structure_order(rows)
        role = role_agnostic_order(rows)
        full, full_scores = evidence_order(
            rows,
            str(selected["evidence_composite"]),
            float(selected["weight"]),
            str(selected["fusion_mode"]),
        )
        rankings = {
            "role_agnostic": role,
            "typed_structure": structure,
            "nested_structure_plus_evidence": full,
        }
        metric_by_model_endpoint: dict[tuple[str, str], dict[str, Any]] = {}
        for endpoint in ENDPOINTS:
            for model, ranked in rankings.items():
                result = band.metrics(ranked, endpoint)
                metric_by_model_endpoint[(model, endpoint)] = result
                metric_rows.append({
                    "cutoff": cutoff,
                    "endpoint": endpoint,
                    "model": model,
                    "selected_evidence_composite": selected["evidence_composite"],
                    "selected_fusion_mode": selected["fusion_mode"],
                    "selected_weight": selected["weight"],
                    **result,
                })

            pairs = popularity_matched_pairs(rows, endpoint)
            scores_by_model = {
                "role_agnostic": {
                    row["trajectory"]: float(row["score_untyped_cooccurrence"])
                    for row in rows
                },
                "typed_structure": {
                    row["trajectory"]: float(row["score_structure_only"])
                    for row in rows
                },
                "nested_structure_plus_evidence": full_scores,
            }
            wins = {model: [] for model in scores_by_model}
            for positive, negative in pairs:
                pair_record = {
                    "cutoff": cutoff,
                    "endpoint": endpoint,
                    "positive_trajectory": positive["trajectory"],
                    "negative_trajectory": negative["trajectory"],
                    "positive_role_score": positive["score_untyped_cooccurrence"],
                    "negative_role_score": negative["score_untyped_cooccurrence"],
                    "positive_node_popularity": positive["score_node_popularity"],
                    "negative_node_popularity": negative["score_node_popularity"],
                }
                for model, score_map in scores_by_model.items():
                    win = comparison(
                        score_map[positive["trajectory"]],
                        score_map[negative["trajectory"]],
                    )
                    wins[model].append(win)
                    pair_record[f"{model}_win"] = win
                pair_rows.append(pair_record)
            for model, values in wins.items():
                match_rows.append({
                    "cutoff": cutoff,
                    "endpoint": endpoint,
                    "model": model,
                    "matched_pairs": len(values),
                    "popularity_matched_pairwise_accuracy": statistics.mean(values),
                })

    summary: dict[str, Any] = {
        "status": "nested_evaluation_complete",
        "outer_cutoffs": list(OUTER_CUTOFFS),
        "selection_is_walk_forward": True,
        "locks": {str(cutoff): locks[cutoff]["selected"] for cutoff in OUTER_CUTOFFS},
    }
    for endpoint in ENDPOINTS:
        short = "validated" if endpoint == PRIMARY_ENDPOINT else "strict"
        structure_rows = {
            int(row["cutoff"]): row for row in metric_rows
            if row["endpoint"] == endpoint and row["model"] == "typed_structure"
        }
        full_rows = {
            int(row["cutoff"]): row for row in metric_rows
            if row["endpoint"] == endpoint
            and row["model"] == "nested_structure_plus_evidence"
        }
        role_rows = {
            int(row["cutoff"]): row for row in metric_rows
            if row["endpoint"] == endpoint and row["model"] == "role_agnostic"
        }
        utility_delta = []
        for k in K_VALUES:
            deltas = [
                int(full_rows[cutoff][f"hits_at_{k}"])
                - int(structure_rows[cutoff][f"hits_at_{k}"])
                for cutoff in OUTER_CUTOFFS
            ]
            summary[f"{short}_mean_delta_hits_at_{k}_vs_structure"] = statistics.mean(deltas)
            summary[f"{short}_nonnegative_cutoffs_at_{k}"] = sum(value >= 0 for value in deltas)
            summary[f"{short}_positive_cutoffs_at_{k}"] = sum(value > 0 for value in deltas)
            summary[f"{short}_per_cutoff_delta_hits_at_{k}"] = deltas
        for cutoff in OUTER_CUTOFFS:
            utility_delta.append(
                head_utility(full_rows[cutoff]) - head_utility(structure_rows[cutoff])
            )
        summary[f"{short}_mean_head_utility_delta_vs_structure"] = statistics.mean(utility_delta)
        summary[f"{short}_mean_delta_ap_vs_structure"] = statistics.mean(
            float(full_rows[cutoff]["average_precision"])
            - float(structure_rows[cutoff]["average_precision"])
            for cutoff in OUTER_CUTOFFS
        )
        summary[f"{short}_mean_hits_at_100"] = {
            "role_agnostic": statistics.mean(int(role_rows[c]["hits_at_100"]) for c in OUTER_CUTOFFS),
            "typed_structure": statistics.mean(int(structure_rows[c]["hits_at_100"]) for c in OUTER_CUTOFFS),
            "nested_structure_plus_evidence": statistics.mean(int(full_rows[c]["hits_at_100"]) for c in OUTER_CUTOFFS),
        }
        matched = {
            row["model"]: [] for row in match_rows if row["endpoint"] == endpoint
        }
        for row in match_rows:
            if row["endpoint"] == endpoint:
                matched[row["model"]].append(float(row["popularity_matched_pairwise_accuracy"]))
        summary[f"{short}_popularity_matched_mean_accuracy"] = {
            model: statistics.mean(values) for model, values in matched.items()
        }

    summary["validated_gain_exceeds_strict"] = (
        float(summary["validated_mean_head_utility_delta_vs_structure"])
        > float(summary["strict_mean_head_utility_delta_vs_structure"])
    )
    summary["validated_popularity_matched_full_exceeds_role"] = (
        float(summary["validated_popularity_matched_mean_accuracy"]["nested_structure_plus_evidence"])
        > float(summary["validated_popularity_matched_mean_accuracy"]["role_agnostic"])
    )
    summary["strict_popularity_matched_full_exceeds_role"] = (
        float(summary["strict_popularity_matched_mean_accuracy"]["nested_structure_plus_evidence"])
        > float(summary["strict_popularity_matched_mean_accuracy"]["role_agnostic"])
    )

    write_csv(output_dir / "nested_metrics.csv", metric_rows)
    write_csv(output_dir / "popularity_matched_metrics.csv", match_rows)
    write_csv(output_dir / "popularity_matched_pairs.csv", pair_rows)
    (output_dir / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    args = parse_args()
    if args.phase == "select":
        run_select(args)
    else:
        run_evaluate(args)


if __name__ == "__main__":
    main()
