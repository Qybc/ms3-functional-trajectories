#!/usr/bin/env python3
"""Prepare aligned porcine ECG and ECG-derived HR tracks for Fig. 5e."""

from __future__ import annotations

import math
import os
import statistics
from pathlib import Path


FIG_DIR = Path(__file__).resolve().parent
PIG_FILE = Path(os.environ.get("MS3_PORCINE_RECORDING", "porcine_recording_not_distributed.txt"))
OUTPUT = FIG_DIR / "fig5_panel_e_porcine_ecg_hr_trace_data_v7_20260907.txt"
HR_SMOOTHING_LABEL = "4-s moving-median HR points"

# All windows come from block 4 of the same acute porcine recording.  The
# baseline window was selected before the first esmolol annotation by a
# prespecified stability audit (low one-second envelope and baseline drift).
# The intervention window follows the 10-ml annotation at 2459.160 s, and the
# pacing window begins at the investigator-labelled 120-bpm marker.
WINDOWS = [
    {
        "label": "Baseline",
        "start": 1671.000,
        "stop": 1701.000,
        "amp_bar": 10.0,
        "plot_min": -10.5,
        "plot_max": 11.5,
        "note": "stable pre-esmolol window selected by raw-envelope audit",
    },
    {
        "label": "Esmolol-induced slowing",
        "start": 2500.000,
        "stop": 2530.000,
        "amp_bar": 10.0,
        "plot_min": -10.5,
        "plot_max": 11.5,
        "note": "stable interval after the 10-ml esmolol annotation at 2459.160 s",
    },
    {
        "label": "120-bpm ventricular pacing after esmolol",
        "start": 3258.395,
        "stop": 3288.395,
        "amp_bar": 10.0,
        "plot_min": -11.5,
        "plot_max": 22.5,
        "note": "begins at the investigator-labelled 120-bpm pacing marker",
    },
]


def extract_windows() -> dict[str, list[tuple[float, float, float]]]:
    selected = {item["label"]: [] for item in WINDOWS}
    block = 0
    with PIG_FILE.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("Interval="):
                block += 1
                continue
            if block != 4:
                continue
            fields = line.rstrip().split("\t")
            if len(fields) < 4:
                continue
            try:
                time = float(fields[0])
                ecg = float(fields[1])
                heart_rate = float(fields[3])
            except ValueError:
                continue
            for item in WINDOWS:
                if item["start"] <= time <= item["stop"]:
                    selected[item["label"]].append((time, ecg, heart_rate))

    for item in WINDOWS:
        rows = selected[item["label"]]
        expected = int(round((item["stop"] - item["start"]) * 1000)) + 1
        if len(rows) != expected:
            raise RuntimeError(
                f"Incomplete {item['label']} window: {len(rows):,}/{expected:,} samples"
            )
        if any(not math.isfinite(value) for row in rows for value in row):
            raise RuntimeError(f"Non-finite values in {item['label']} window")
    return selected


def minmax_decimate(
    rows: list[tuple[float, float, float]], start: float, stop: float, bucket: int = 10
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for offset in range(0, len(rows), bucket):
        chunk = list(enumerate(rows[offset : offset + bucket], offset))
        if not chunk:
            continue
        low = min(chunk, key=lambda item: item[1][1])
        high = max(chunk, key=lambda item: item[1][1])
        for _, (time, ecg, _) in sorted((low, high), key=lambda item: item[0]):
            points.append(((time - start) / (stop - start), ecg))
    return points


def smoothed_hr(
    rows: list[tuple[float, float, float]], start: float, stop: float
) -> list[tuple[float, float]]:
    """Return a 4-s moving-median display track sampled every 0.25 s."""
    sampled: list[tuple[float, float]] = []
    cursor = 0
    for index in range(0, len(rows), 250):
        time = rows[index][0]
        while cursor < len(rows) and rows[cursor][0] < time - 2.0:
            cursor += 1
        end = cursor
        while end < len(rows) and rows[end][0] <= time + 2.0:
            end += 1
        heart_rate = statistics.median(row[2] for row in rows[cursor:end])
        sampled.append(((time - start) / (stop - start), heart_rate))
    if sampled[-1][0] < 1.0:
        sampled.append((1.0, sampled[-1][1]))
    return sampled


def encode(points: list[tuple[float, float]]) -> str:
    return ";".join(f"{x:.7f},{y:.7f}" for x, y in points)


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite {OUTPUT}")
    selected = extract_windows()
    lines = [
        "# label|duration_s|amplitude_bar_mV|plot_min_mV|plot_max_mV|source|block|start_s|stop_s|note|ECG points|"
        + HR_SMOOTHING_LABEL,
        "# all windows: 1 kHz, 30.000 s, 30,001 samples, zero missing values; HR is the acquisition system's ECG-derived channel",
    ]
    for item in WINDOWS:
        rows = selected[item["label"]]
        ecg_points = minmax_decimate(rows, item["start"], item["stop"])
        hr_points = smoothed_hr(rows, item["start"], item["stop"])
        heart_rates = [row[2] for row in rows]
        ecg_values = [row[1] for row in rows]
        lines.append(
            "|".join(
                [
                    item["label"],
                    f"{item['stop'] - item['start']:.3f}",
                    f"{item['amp_bar']:.3f}",
                    f"{item['plot_min']:.3f}",
                    f"{item['plot_max']:.3f}",
                    PIG_FILE.name,
                    "4",
                    f"{item['start']:.3f}",
                    f"{item['stop']:.3f}",
                    item["note"],
                    encode(ecg_points),
                    encode(hr_points),
                ]
            )
        )
        print(
            f"{item['label']}: ECG {min(ecg_values):.3f} to {max(ecg_values):.3f} mV; "
            f"HR median {statistics.median(heart_rates):.1f} bpm; "
            f"{len(ecg_points):,} ECG and {len(hr_points):,} HR display points"
        )
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
