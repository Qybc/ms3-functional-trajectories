#!/usr/bin/env python3
"""Recalculate central reported values from the public MS³ data package."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def close(observed: float, expected: float, tolerance: float = 1e-9) -> None:
    if abs(observed - expected) > tolerance:
        raise AssertionError(f"{observed} != {expected}")


def innovation_composition(root: Path) -> dict[str, object]:
    aggregate_rows = read_csv(
        root
        / "data/fig3_innovation_backtesting/new_complete_trajectories_2022_2025.csv"
    )
    row_level = read_csv(
        root
        / "data/fig3_innovation_backtesting/new_complete_trajectories_2022_2025_row_level.csv"
    )
    class_for_mode = {
        "Higher-order recombination": "All three local links pre-observed",
        "Material implementation": "Material-to-Sensor only",
        "Transduction novelty": "Sensor-to-Signal only",
        "Application transfer": "Signal-to-System only",
        "Multi-layer novelty": "Multi-layer novelty",
    }
    counts = {label: 0 for label in class_for_mode.values()}
    unique_trajectories: set[str] = set()
    for row in row_level:
        mode = row["mode"]
        if mode not in class_for_mode:
            raise AssertionError(f"Unexpected trajectory mode: {mode}")
        trajectory = row["trajectory"]
        if trajectory in unique_trajectories:
            raise AssertionError(f"Duplicate row-level trajectory: {trajectory}")
        unique_trajectories.add(trajectory)
        counts[class_for_mode[mode]] += 1
    aggregate_counts = {
        row["class"]: int(row["count"]) for row in aggregate_rows
    }
    if counts != aggregate_counts:
        raise AssertionError(
            f"Row-level and aggregate innovation counts differ: {counts} != {aggregate_counts}"
        )
    total = sum(counts.values())
    recombined = counts["All three local links pre-observed"]
    percent = 100.0 * recombined / total
    reported = float(
        next(
            row["percent"]
            for row in aggregate_rows
            if row["class"] == "All three local links pre-observed"
        )
    )
    close(round(percent, 1), reported)
    return {
        "new_complete_trajectories": total,
        "all_three_local_links_pre_observed": recombined,
        "recombination_percent": round(percent, 1),
    }


def benchmark_summary(root: Path) -> dict[str, object]:
    rows = read_csv(root / "data/fig2_agent_evaluation/benchmark_summary.csv")
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["benchmark"]].append(row)
    if len(grouped) != 4 or any(len(values) != 6 for values in grouped.values()):
        raise AssertionError("Expected four benchmarks and six methods per benchmark")
    return {
        name: {
            "n_items": int(values[0]["n_items"]),
            "ms3_agent_score_percent": float(
                next(row["score_percent"] for row in values if row["method"] == "MS3 Agent")
            ),
        }
        for name, values in sorted(grouped.items())
    }


def fs_evidenceqa(root: Path) -> dict[str, object]:
    item_rows = read_csv(
        root / "data/fig2_agent_evaluation/fs_evidenceqa_per_item_scores.csv"
    )
    summary_rows = read_csv(
        root / "data/fig2_agent_evaluation/fs_evidenceqa_method_summary.csv"
    )
    values: dict[str, list[float]] = defaultdict(list)
    cases: dict[str, set[str]] = defaultdict(set)
    for row in item_rows:
        values[row["method"]].append(float(row["normalized_percent"]))
        cases[row["method"]].add(row["case_id"])
    reported = {row["method"]: row for row in summary_rows}
    result: dict[str, object] = {}
    for method in sorted(values):
        if len(values[method]) != 120 or len(cases[method]) != 120:
            raise AssertionError(f"{method} does not contain 120 unique cases")
        observed = statistics.mean(values[method])
        close(observed, float(reported[method]["normalized_percent"]))
        result[method] = {
            "n_items": len(values[method]),
            "normalized_percent": observed,
        }
    return result


def historical_top100(root: Path) -> dict[str, object]:
    rows = read_csv(
        root / "data/fig3_innovation_backtesting/top100_closure_summary.csv"
    )
    ranked_rows = read_csv(
        root / "data/fig3_innovation_backtesting/ranked_top100_candidates.csv"
    )
    endpoints: dict[str, dict[str, list[int]]] = {}
    for endpoint in ("closed_in_future", "validated_closure"):
        subset = [row for row in rows if row["endpoint"] == endpoint]
        cutoffs = sorted({int(row["cutoff"]) for row in subset})
        if cutoffs != [2018, 2019, 2020, 2021]:
            raise AssertionError(f"Unexpected cutoffs for {endpoint}: {cutoffs}")
        models: dict[str, list[int]] = {}
        for model in (
            "role_agnostic",
            "typed_structure",
            "nested_structure_plus_evidence",
        ):
            indexed = {
                int(row["cutoff"]): int(row["top100_hits"])
                for row in subset
                if row["model"] == model
            }
            models[model] = [indexed[cutoff] for cutoff in cutoffs]
            for cutoff in cutoffs:
                candidates = [
                    row
                    for row in ranked_rows
                    if int(row["cutoff"]) == cutoff and row["method"] == model
                ]
                if len(candidates) != 100:
                    raise AssertionError(
                        f"Expected 100 candidate rows for {cutoff}/{model}; found {len(candidates)}"
                    )
                ranks = sorted(int(row["rank"]) for row in candidates)
                if ranks != list(range(1, 101)):
                    raise AssertionError(f"Non-contiguous ranks for {cutoff}/{model}")
                candidate_hits = sum(int(row[endpoint]) for row in candidates)
                if candidate_hits != indexed[cutoff]:
                    raise AssertionError(
                        f"Candidate and summary hits differ for {endpoint}/{cutoff}/{model}: "
                        f"{candidate_hits} != {indexed[cutoff]}"
                    )
        endpoints[endpoint] = models
    return {"cutoffs": [2018, 2019, 2020, 2021], "top100_hits": endpoints}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recalculate central MS³ results from released CSV files."
    )
    parser.add_argument(
        "release_root", nargs="?", type=Path, default=Path("."),
        help="root of the MS³ data and code package",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()
    root = args.release_root.resolve()

    result = {
        "innovation_composition": innovation_composition(root),
        "benchmark_summary": benchmark_summary(root),
        "fs_evidenceqa": fs_evidenceqa(root),
        "historical_backtesting": historical_top100(root),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    innovation = result["innovation_composition"]
    print(
        "Innovation composition: "
        f"{innovation['all_three_local_links_pre_observed']}/"
        f"{innovation['new_complete_trajectories']} = "
        f"{innovation['recombination_percent']:.1f}%"
    )
    print("\nMS³ Agent benchmark scores:")
    for benchmark, values in result["benchmark_summary"].items():
        print(
            f"  {benchmark}: {values['ms3_agent_score_percent']:.1f}% "
            f"(n={values['n_items']})"
        )
    print("\nFS EvidenceQA recalculated means:")
    for method, values in result["fs_evidenceqa"].items():
        print(f"  {method}: {values['normalized_percent']:.3f}%")
    historical = result["historical_backtesting"]
    print("\nHistorical Top-100 hits by 2018–2021 cutoff:")
    for endpoint, models in historical["top100_hits"].items():
        print(f"  {endpoint}:")
        for model, hits in models.items():
            print(f"    {model}: {hits}")
    print("\nverification: PASS")


if __name__ == "__main__":
    main()
