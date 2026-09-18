#!/usr/bin/env python3
"""Prepare Fig. 5e ECG/HR tracks with a robust 6-s HR display median."""

from pathlib import Path
import statistics

import prepare_fig5_panel_e_porcine_ecg_hr_v7_20260907 as base


base.OUTPUT = (
    Path(__file__).resolve().parent
    / "fig5_panel_e_porcine_ecg_hr_trace_data_v8_20260907.txt"
)
base.HR_SMOOTHING_LABEL = "6-s moving-median HR points"


def smoothed_hr(rows, start, stop):
    """Suppress isolated ECG-rate detector errors with a 6-s moving median."""
    sampled = []
    cursor = 0
    for index in range(0, len(rows), 250):
        time = rows[index][0]
        while cursor < len(rows) and rows[cursor][0] < time - 3.0:
            cursor += 1
        end = cursor
        while end < len(rows) and rows[end][0] <= time + 3.0:
            end += 1
        heart_rate = statistics.median(row[2] for row in rows[cursor:end])
        sampled.append(((time - start) / (stop - start), heart_rate))
    if sampled[-1][0] < 1.0:
        sampled.append((1.0, sampled[-1][1]))
    return sampled


base.smoothed_hr = smoothed_hr


if __name__ == "__main__":
    base.main()
