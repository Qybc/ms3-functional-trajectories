#!/usr/bin/env python3
"""Evaluate retrieval and context-efficiency benefits of frozen MS³ paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sqlite3
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[./+-][A-Za-z0-9]+)*|[\u4e00-\u9fff]")
EVIDENCE_PATTERN = re.compile(r"\bE\d+\b", re.I)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "based", "by", "can", "compare", "device",
    "evidence", "evidence-supported", "find", "for", "from", "in", "including", "into", "is",
    "it", "material", "of", "on", "one", "or", "paper", "path", "reported", "route", "sensor",
    "sensing", "signal", "study", "system", "that", "the", "their", "this", "to", "two", "used",
    "using", "via", "where", "which", "with",
}
GENERIC_PAIR_TERMS = STOPWORDS | {
    "application", "change", "detection", "electrical", "flexible", "high", "human", "measurement",
    "monitoring", "performance", "pressure", "real-time", "response", "sensitivity", "wearable",
}
CONTROLLED_BRIDGE_TERMS = set(
    """
    piezoresistive capacitive capacitance resistance resistive impedance current voltage electrochemical
    amperometric potentiometric conductometric triboelectric piezoelectric inductive optical fluorescence
    fluorescent luminescence phosphorescence plasmonic colorimetric raman magnetic hall thermal temperature
    humidity pressure strain tactile force bending motion glucose lactate sweat gas oxygen ammonia nitrogen
    biosensing biochemical photodetector transistor fet ofet memristor antenna microwave resonant resonance
    acoustic ultrasonic fiber-optic hydrogel mxene graphene cnt nanofiber textile wearable e-skin iontronic
    dielectric redox enzymatic adsorption swelling contact percolation tunneling lspr spr photonic
    electrochromic thermochromic photochromic uv
    """.split()
)
CONTEXT_BUDGETS = (1000, 2000, 4000, 8000)
RANK_CUTOFFS = (1, 5, 10, 20)


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def sha256_json(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def tokens(value: Any, stopwords: set[str] | None = None) -> list[str]:
    blocked = STOPWORDS if stopwords is None else stopwords
    found: list[str] = []
    seen: set[str] = set()
    for token in TOKEN_PATTERN.findall(clean(value).lower()):
        if len(token) < 2 or token in blocked or token in seen or token.isdigit():
            continue
        seen.add(token)
        found.append(token)
    return found


def hint(value: Any, limit: int = 9) -> str:
    selected = tokens(value)[:limit]
    return " ".join(selected)


def fts_query(value: str, max_terms: int = 40) -> str:
    selected = tokens(value)[:max_terms]
    if not selected:
        raise ValueError(f"No searchable terms in query: {value}")
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in selected)


def evidence_ids(raw: Any) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in EVIDENCE_PATTERN.findall(clean(raw)):
        key = match.upper()
        if key not in seen:
            seen.add(key)
            found.append(key)
    return found


def valid_field(value: Any) -> bool:
    text = clean(value)
    lowered = text.lower()
    return 3 <= len(text) <= 800 and lowered not in {"none", "not reported", "not specified", "n/a", "unknown"}


def bootstrap_ci(values: list[float], seed: str, iterations: int = 5000) -> list[float | None]:
    if not values:
        return [None, None]
    rng = random.Random(seed)
    means = [statistics.fmean(rng.choice(values) for _ in values) for _ in range(iterations)]
    means.sort()

    def percentile(q: float) -> float:
        position = (len(means) - 1) * q
        lo, hi = math.floor(position), math.ceil(position)
        if lo == hi:
            return means[lo]
        return means[lo] * (hi - position) + means[hi] * (position - lo)

    return [percentile(0.025), percentile(0.975)]


def first_rank(items: Iterable[dict[str, Any]], key: str, gold: str) -> int | None:
    for index, item in enumerate(items, 1):
        if clean(item.get(key)).upper() == gold.upper():
            return index
    return None


def ranked_unique_papers(items: Iterable[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        paper_id = clean(item.get("paper_id"))
        if paper_id and paper_id not in seen:
            seen.add(paper_id)
            result.append(paper_id)
    return result


def rank_of_value(values: Iterable[str], gold: str) -> int | None:
    for index, value in enumerate(values, 1):
        if value.upper() == gold.upper():
            return index
    return None


def reciprocal(rank: int | None) -> float:
    return 0.0 if rank is None else 1.0 / rank


def serialized_size(method: str, item: dict[str, Any]) -> int:
    if method == "text_bm25":
        payload = {
            key: item.get(key)
            for key in ("paper_id", "evidence_id", "title", "section", "evidence_type", "article_excerpt_text")
        }
    else:
        payload = {
            key: item.get(key)
            for key in (
                "paper_id", "mechanism_id", "title", "mechanism_statement", "material", "sensor", "signal",
                "system", "linked_evidence_ids",
            )
        }
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def budget_hits(method: str, items: list[dict[str, Any]], gold_papers: set[str]) -> dict[str, int]:
    hits = {str(budget): 0 for budget in CONTEXT_BUDGETS}
    used = 2
    observed: set[str] = set()
    for item in items:
        size = serialized_size(method, item) + 1
        for budget in CONTEXT_BUDGETS:
            if used + size <= budget:
                if item.get("paper_id") in gold_papers:
                    hits[str(budget)] = 1
        used += size
        if item.get("paper_id") in gold_papers:
            observed.add(item["paper_id"])
        if used > max(CONTEXT_BUDGETS) and observed >= gold_papers:
            break
    return hits


class Searcher:
    def __init__(self, db_path: Path) -> None:
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    def text(self, query: str, limit: int = 200) -> tuple[list[dict[str, Any]], float]:
        started = time.perf_counter()
        rows = self.conn.execute(
            """
            select f.evidence_uid,f.paper_id,e.evidence_id,p.title,e.section,e.evidence_type,
                   e.article_excerpt_text,bm25(evidence_fts) as retrieval_score
            from evidence_fts f
            join evidence e on e.evidence_uid=f.evidence_uid
            join papers p on p.paper_id=f.paper_id
            where evidence_fts match ?
            order by retrieval_score
            limit ?
            """,
            (fts_query(query), limit),
        ).fetchall()
        return [dict(row) for row in rows], time.perf_counter() - started

    def ms3(self, query: str, limit: int = 200) -> tuple[list[dict[str, Any]], float]:
        started = time.perf_counter()
        rows = self.conn.execute(
            """
            select f.mechanism_uid,f.paper_id,m.mechanism_id,p.title,m.mechanism_statement,
                   m.material,m.sensor,m.signal,m.system,m.evidence_chain_json,
                   bm25(mechanism_fts) as retrieval_score
            from mechanism_fts f
            join mechanisms m on m.mechanism_uid=f.mechanism_uid
            join papers p on p.paper_id=f.paper_id
            where mechanism_fts match ?
            order by retrieval_score
            limit ?
            """,
            (fts_query(query), limit),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["linked_evidence_ids"] = evidence_ids(item.pop("evidence_chain_json", ""))
            result.append(item)
        return result, time.perf_counter() - started


def load_excluded_papers(sourcebook: Path | None, prior_benchmarks: list[Path]) -> set[str]:
    excluded: set[str] = set()
    if sourcebook:
        data = json.loads(sourcebook.read_text(encoding="utf-8"))
        excluded.update(
            clean(paper_id)
            for case in data.get("cases", [])
            for paper_id in case.get("source_paper_ids", [])
            if clean(paper_id)
        )
    for path in prior_benchmarks:
        data = json.loads(path.read_text(encoding="utf-8"))
        excluded.update(
            clean(paper_id)
            for group in ("single_cases", "pair_cases")
            for case in data.get(group, [])
            for paper_id in case.get("gold_paper_ids", [])
            if clean(paper_id)
        )
    return excluded


def load_eligible(conn: sqlite3.Connection, excluded: set[str]) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        select m.mechanism_uid,m.paper_id,m.mechanism_id,m.mechanism_statement,m.material,m.sensor,m.signal,m.system,
               m.evidence_chain_json,p.corpus_domain,p.primary_task
        from mechanisms m join papers p using(paper_id)
        where m.material!='' and m.sensor!='' and m.signal!='' and m.system!=''
        order by m.mechanism_uid
        """
    ).fetchall()
    result = []
    for raw in rows:
        row = dict(raw)
        if row["paper_id"] in excluded or not all(valid_field(row[field]) for field in ("material", "sensor", "signal", "system")):
            continue
        linked = evidence_ids(row.get("evidence_chain_json"))
        if not linked:
            continue
        row["linked_evidence_ids"] = linked
        result.append(row)
    return result


def build_single_cases(eligible: list[dict[str, Any]], count: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    selected = rng.sample(eligible, min(count, len(eligible)))
    cases = []
    for index, row in enumerate(selected, 1):
        variants = (
            (
                "material_system",
                f"Find evidence-supported sensing studies connecting {hint(row['material'])} to {hint(row['system'])}.",
            ),
            (
                "sensor_signal",
                f"Find evidence-supported studies where {hint(row['sensor'])} produces {hint(row['signal'])}.",
            ),
            (
                "material_signal",
                f"Find evidence-supported sensing routes connecting {hint(row['material'])} to {hint(row['signal'])}.",
            ),
            (
                "sensor_signal_system",
                f"Find evidence-supported paths where {hint(row['sensor'])} produces {hint(row['signal'])} for {hint(row['system'])}.",
            ),
        )
        query_variant, query = variants[(index - 1) % len(variants)]
        cases.append(
            {
                "case_id": f"single_{index:04d}",
                "query": query,
                "query_variant": query_variant,
                "gold_paper_ids": [row["paper_id"]],
                "gold_mechanism_uid": row["mechanism_uid"],
                "gold_mechanism_id": row["mechanism_id"],
                "gold_evidence_ids": [f"{row['paper_id']}:{item}" for item in row["linked_evidence_ids"]],
                "stratum": clean(row.get("corpus_domain") or row.get("primary_task") or "unspecified"),
            }
        )
    return cases


def build_pair_cases(eligible: list[dict[str, Any]], count: int, seed: int) -> list[dict[str, Any]]:
    token_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        for token in set(tokens(f"{row['sensor']} {row['signal']} {row['system']}", set())):
            if token not in CONTROLLED_BRIDGE_TERMS:
                continue
            token_rows[token].append(row)
    candidate_tokens = sorted(
        token for token, rows in token_rows.items()
        if 8 <= len({row["paper_id"] for row in rows}) <= 500
    )
    rng = random.Random(seed)
    rng.shuffle(candidate_tokens)
    cases = []
    used_pairs: set[tuple[str, str]] = set()
    for token in candidate_tokens:
        rows = list(token_rows[token])
        rng.shuffle(rows)
        added_for_token = 0
        for left_index, left in enumerate(rows):
            for right in rows[left_index + 1 :]:
                if left["paper_id"] == right["paper_id"]:
                    continue
                pair = tuple(sorted((left["mechanism_uid"], right["mechanism_uid"])))
                if pair in used_pairs:
                    continue
                left_hint, right_hint = hint(left["material"], 4), hint(right["material"], 4)
                if not left_hint or not right_hint or left_hint == right_hint:
                    continue
                used_pairs.add(pair)
                cases.append(
                    {
                        "case_id": f"pair_{len(cases) + 1:04d}",
                        "query": (
                            f"Find and compare two evidence-supported MS3 paths involving {token}: "
                            f"one based on {left_hint} and another based on {right_hint}."
                        ),
                        "bridge_term": token,
                        "gold_paper_ids": [left["paper_id"], right["paper_id"]],
                        "gold_mechanism_uids": [left["mechanism_uid"], right["mechanism_uid"]],
                    }
                )
                added_for_token += 1
                break
            if len(cases) >= count:
                return cases
            if added_for_token >= 3:
                break
        if len(cases) >= count:
            break
    return cases


def build_benchmark(
    db_path: Path,
    sourcebook: Path | None,
    prior_benchmarks: list[Path],
    single_count: int,
    pair_count: int,
    seed: int,
) -> dict[str, Any]:
    excluded = load_excluded_papers(sourcebook, prior_benchmarks)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        eligible = load_eligible(conn, excluded)
    finally:
        conn.close()
    single = build_single_cases(eligible, single_count, seed)
    pair = build_pair_cases(eligible, pair_count, seed + 1)
    benchmark = {
        "benchmark_id": f"ms3_structural_advantage_seed{seed}",
        "seed": seed,
        "construction": "known-item queries from frozen complete MS3 paths; no title/DOI/ID; prior Fig4 papers excluded",
        "excluded_paper_count": len(excluded),
        "eligible_mechanism_count": len(eligible),
        "single_cases": single,
        "pair_cases": pair,
    }
    benchmark["sha256"] = sha256_json(benchmark)
    return benchmark


def evaluate_single(searcher: Searcher, cases: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    results = []
    for index, case in enumerate(cases, 1):
        text_rows, text_seconds = searcher.text(case["query"], limit)
        ms3_rows, ms3_seconds = searcher.ms3(case["query"], limit)
        gold_paper = case["gold_paper_ids"][0]
        text_papers = ranked_unique_papers(text_rows)
        ms3_papers = ranked_unique_papers(ms3_rows)
        text_evidence = [f"{row['paper_id']}:{clean(row['evidence_id']).upper()}" for row in text_rows]
        routed_evidence = []
        seen_evidence = set()
        for row in ms3_rows:
            for evidence_id in row.get("linked_evidence_ids", []):
                citation = f"{row['paper_id']}:{evidence_id.upper()}"
                if citation not in seen_evidence:
                    seen_evidence.add(citation)
                    routed_evidence.append(citation)
        gold_evidence = set(case["gold_evidence_ids"])
        row = {
            "case_id": case["case_id"],
            "query": case["query"],
            "gold_paper_id": gold_paper,
            "text_paper_rank": rank_of_value(text_papers, gold_paper),
            "ms3_paper_rank": rank_of_value(ms3_papers, gold_paper),
            "ms3_mechanism_rank": first_rank(ms3_rows, "mechanism_uid", case["gold_mechanism_uid"]),
            "text_evidence_any_rank": min(
                (rank for citation in gold_evidence if (rank := rank_of_value(text_evidence, citation)) is not None),
                default=None,
            ),
            "ms3_linked_evidence_any_rank": min(
                (rank for citation in gold_evidence if (rank := rank_of_value(routed_evidence, citation)) is not None),
                default=None,
            ),
            "text_context_hits": budget_hits("text_bm25", text_rows, {gold_paper}),
            "ms3_context_hits": budget_hits("ms3_bm25", ms3_rows, {gold_paper}),
            "text_seconds": text_seconds,
            "ms3_seconds": ms3_seconds,
            "text_top20_papers": text_papers[:20],
            "ms3_top20_papers": ms3_papers[:20],
        }
        for cutoff in (10, 20, 50):
            row[f"text_evidence_recall_{cutoff}"] = len(gold_evidence & set(text_evidence[:cutoff])) / len(gold_evidence)
            row[f"ms3_linked_evidence_recall_{cutoff}"] = len(gold_evidence & set(routed_evidence[:cutoff])) / len(gold_evidence)
        results.append(row)
        if index % 25 == 0 or index == len(cases):
            print(f"single {index}/{len(cases)}", flush=True)
    return results


def evaluate_pairs(searcher: Searcher, cases: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    results = []
    for index, case in enumerate(cases, 1):
        text_rows, text_seconds = searcher.text(case["query"], limit)
        ms3_rows, ms3_seconds = searcher.ms3(case["query"], limit)
        gold = set(case["gold_paper_ids"])
        text_papers, ms3_papers = ranked_unique_papers(text_rows), ranked_unique_papers(ms3_rows)
        row = {
            "case_id": case["case_id"],
            "query": case["query"],
            "bridge_term": case["bridge_term"],
            "gold_paper_ids": case["gold_paper_ids"],
            "text_seconds": text_seconds,
            "ms3_seconds": ms3_seconds,
            "text_context_hits": budget_hits("text_bm25", text_rows, gold),
            "ms3_context_hits": budget_hits("ms3_bm25", ms3_rows, gold),
            "text_top50_papers": text_papers[:50],
            "ms3_top50_papers": ms3_papers[:50],
        }
        for cutoff in (2, 5, 10, 20, 50):
            row[f"text_pair_recall_{cutoff}"] = len(gold & set(text_papers[:cutoff])) / 2
            row[f"ms3_pair_recall_{cutoff}"] = len(gold & set(ms3_papers[:cutoff])) / 2
            row[f"text_both_{cutoff}"] = int(gold <= set(text_papers[:cutoff]))
            row[f"ms3_both_{cutoff}"] = int(gold <= set(ms3_papers[:cutoff]))
        results.append(row)
        if index % 25 == 0 or index == len(cases):
            print(f"pair {index}/{len(cases)}", flush=True)
    return results


def mean_metric(rows: list[dict[str, Any]], key: str) -> float:
    return statistics.fmean(float(row[key]) for row in rows)


def paired_summary(rows: list[dict[str, Any]], text_key: str, ms3_key: str, seed: str) -> dict[str, Any]:
    text_values = [float(row[text_key]) for row in rows]
    ms3_values = [float(row[ms3_key]) for row in rows]
    deltas = [ms3 - text for text, ms3 in zip(text_values, ms3_values)]
    return {
        "text_mean": statistics.fmean(text_values),
        "ms3_mean": statistics.fmean(ms3_values),
        "ms3_minus_text": statistics.fmean(deltas),
        "delta_ci95": bootstrap_ci(deltas, seed),
        "wins": sum(value > 0 for value in deltas),
        "ties": sum(value == 0 for value in deltas),
        "losses": sum(value < 0 for value in deltas),
    }


def summarize(single: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"single_case_count": len(single), "pair_case_count": len(pairs), "single": {}, "pairs": {}}
    for cutoff in RANK_CUTOFFS:
        for method in ("text", "ms3"):
            for row in single:
                rank = row[f"{method}_paper_rank"]
                row[f"{method}_paper_hit_{cutoff}"] = int(rank is not None and rank <= cutoff)
        summary["single"][f"paper_recall_at_{cutoff}"] = paired_summary(
            single, f"text_paper_hit_{cutoff}", f"ms3_paper_hit_{cutoff}", f"paper@{cutoff}"
        )
    for method in ("text", "ms3"):
        for row in single:
            row[f"{method}_paper_rr"] = reciprocal(row[f"{method}_paper_rank"])
    summary["single"]["paper_mrr"] = paired_summary(single, "text_paper_rr", "ms3_paper_rr", "paper_mrr")
    for cutoff in (10, 20, 50):
        summary["single"][f"evidence_recall_at_{cutoff}"] = paired_summary(
            single, f"text_evidence_recall_{cutoff}", f"ms3_linked_evidence_recall_{cutoff}", f"evidence@{cutoff}"
        )
    for cutoff in (2, 5, 10, 20, 50):
        summary["pairs"][f"pair_recall_at_{cutoff}"] = paired_summary(
            pairs, f"text_pair_recall_{cutoff}", f"ms3_pair_recall_{cutoff}", f"pair_recall@{cutoff}"
        )
        summary["pairs"][f"both_papers_at_{cutoff}"] = paired_summary(
            pairs, f"text_both_{cutoff}", f"ms3_both_{cutoff}", f"pair_both@{cutoff}"
        )
    for budget in CONTEXT_BUDGETS:
        text_key, ms3_key = f"text_budget_{budget}", f"ms3_budget_{budget}"
        for row in single:
            row[text_key] = row["text_context_hits"][str(budget)]
            row[ms3_key] = row["ms3_context_hits"][str(budget)]
        summary["single"][f"context_hit_at_{budget}_chars"] = paired_summary(
            single, text_key, ms3_key, f"context@{budget}"
        )
    summary["single"]["latency_seconds"] = paired_summary(single, "text_seconds", "ms3_seconds", "latency_single")
    summary["pairs"]["latency_seconds"] = paired_summary(pairs, "text_seconds", "ms3_seconds", "latency_pair")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--sourcebook", type=Path)
    parser.add_argument("--exclude-benchmark", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--single-count", type=int, default=400)
    parser.add_argument("--pair-count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260809)
    parser.add_argument("--retrieval-limit", type=int, default=200)
    parser.add_argument("--benchmark-only", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    benchmark = build_benchmark(
        args.db, args.sourcebook, args.exclude_benchmark, args.single_count, args.pair_count, args.seed
    )
    write_json(args.output_dir / "benchmark_frozen.json", benchmark)
    print(
        f"Frozen {len(benchmark['single_cases'])} single and {len(benchmark['pair_cases'])} pair cases; "
        f"sha256={benchmark['sha256']}",
        flush=True,
    )
    if args.benchmark_only:
        return 0
    searcher = Searcher(args.db)
    try:
        single = evaluate_single(searcher, benchmark["single_cases"], args.retrieval_limit)
        pairs = evaluate_pairs(searcher, benchmark["pair_cases"], args.retrieval_limit)
    finally:
        searcher.close()
    summary = summarize(single, pairs)
    result = {
        "status": "automatic known-item structural-advantage benchmark complete; new runs require expert confirmation",
        "benchmark_sha256": benchmark["sha256"],
        "database_file": args.db.name,
        "methods": ["text_bm25", "ms3_bm25", "ms3_linked_evidence"],
        "summary": summary,
        "single_results": single,
        "pair_results": pairs,
    }
    result["run_sha256"] = sha256_json(result)
    write_json(args.output_dir / "results.json", result)
    write_json(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
