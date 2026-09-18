#!/usr/bin/env python3
"""Run the bounded MS3 scientific agent against a frozen read-only database.

The agent begins with a question and an empty workspace. It can search stored
functional trajectories, inspect multi-paper paths and open exact linked article
evidence before producing a citation-audited answer. The historical experiment
identifier is retained in output metadata for compatibility with frozen runs.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import socket
import sqlite3
import statistics
import sys
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


HERE = Path(__file__).resolve().parent
for import_path in (str(HERE),):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from run_fig4_factorial import (  # noqa: E402
    ChatClient,
    FINAL_SCHEMA_TEXT,
    canonical_citations,
    clean,
    normalize_final,
    sha256_json,
    write_json,
)
from run_structural_advantage_benchmark import Searcher, tokens  # noqa: E402


WRITE_LOCK = threading.Lock()
EVIDENCE_PATTERN = re.compile(r"\bE\d+\b", re.I)
METHOD_ID = "ms3_global_agent_v2"
ALLOWED_ACTIONS = ("search_ms3", "trace_paths", "inspect_evidence", "final")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def linked_evidence_ids(value: Any) -> List[str]:
    found: List[str] = []
    seen: Set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        else:
            for match in EVIDENCE_PATTERN.findall(clean(item)):
                key = match.upper()
                if key not in seen:
                    seen.add(key)
                    found.append(key)

    walk(parse_json(value, value))
    return found


def source_location(raw_json: Any) -> Dict[str, Any]:
    raw = parse_json(raw_json, {})
    source = raw.get("source", {}) if isinstance(raw, dict) else {}
    return {
        "page": source.get("page") or source.get("page_number") or source.get("pdf_page"),
        "section": clean(source.get("section")),
        "figure_or_table": clean(source.get("figure_or_table")),
    }


def canonical_id(paper_id: str, record_id: str) -> str:
    return f"{clean(paper_id)}:{clean(record_id).upper()}".upper()


def overlap_score(query: str, row: Dict[str, Any]) -> float:
    query_tokens = set(tokens(query))
    text = " ".join(
        clean(row.get(key))
        for key in ("title", "mechanism_statement", "material", "sensor", "signal", "system")
    )
    return len(query_tokens & set(tokens(text))) / max(1, len(query_tokens))


def complete_role_path(row: Dict[str, Any]) -> bool:
    invalid = {"", "none", "not reported", "not specified", "n/a", "unknown"}
    return all(clean(row.get(field)).lower() not in invalid for field in ("material", "sensor", "signal", "system"))


def clip_text(value: Any, limit: int) -> str:
    text = clean(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fit_observation(value: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded) <= max_chars:
        return value
    for key in ("paths", "evidence", "results"):
        records = value.get(key)
        if not isinstance(records, list):
            continue
        selected: List[Dict[str, Any]] = []
        for record in records:
            candidate = dict(value)
            candidate[key] = [*selected, record]
            candidate["truncated"] = True
            if len(json.dumps(candidate, ensure_ascii=False)) > max_chars:
                break
            selected.append(record)
        trimmed = dict(value)
        trimmed[key] = selected
        trimmed["truncated"] = len(selected) < len(records)
        return trimmed
    return {"warning": "observation exceeded ceiling", "snippet": encoded[: max(0, max_chars - 100)]}


class GlobalMS3Toolbox:
    """Deterministic, read-only tools over the complete frozen SQLite corpus."""

    def __init__(self, db_path: Path, question: str, max_observation_chars: int = 18000) -> None:
        self.db_path = db_path
        self.question = question
        self.max_observation_chars = max_observation_chars
        self.searcher = Searcher(db_path)
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        self.workspace_papers: Dict[str, Dict[str, Any]] = {}
        self.exposed_mechanism_ids: Set[str] = set()
        self.exposed_evidence_ids: Set[str] = set()
        self.opened_evidence_ids: Set[str] = set()
        self.evidence_targets: Dict[str, Tuple[str, str]] = {}
        self.action_counts: Counter[str] = Counter()
        self.action_sequence: List[str] = []
        self.counts = {
            "papers": int(self.conn.execute("select count(*) from papers").fetchone()[0]),
            "mechanisms": int(self.conn.execute("select count(*) from mechanisms").fetchone()[0]),
            "evidence": int(self.conn.execute("select count(*) from evidence").fetchone()[0]),
        }

    def close(self) -> None:
        self.searcher.close()
        self.conn.close()

    def _paper(self, paper_id: str) -> Dict[str, Any]:
        if paper_id in self.workspace_papers:
            return self.workspace_papers[paper_id]
        row = self.conn.execute(
            "select paper_id,title,doi,year,paper_type from papers where paper_id=?", (paper_id,)
        ).fetchone()
        if row is None:
            return {"paper_id": paper_id}
        paper = {key: row[key] for key in row.keys()}
        self.workspace_papers[paper_id] = paper
        return paper

    def _expose_evidence(self, paper_id: str, evidence_id: str, opened: bool = False) -> str:
        citation = canonical_id(paper_id, evidence_id)
        self.exposed_evidence_ids.add(citation)
        self.evidence_targets[citation] = (paper_id, clean(evidence_id).upper())
        if opened:
            self.opened_evidence_ids.add(citation)
        return citation

    def _compact_path(self, row: Dict[str, Any], full: bool = False) -> Dict[str, Any]:
        paper_id = clean(row.get("paper_id"))
        mechanism_id = clean(row.get("mechanism_id")).upper()
        citation = canonical_id(paper_id, mechanism_id)
        self.exposed_mechanism_ids.add(citation)
        paper = self._paper(paper_id)
        evidence_ids = row.get("linked_evidence_ids") or linked_evidence_ids(row.get("evidence_chain_json"))
        linked = [self._expose_evidence(paper_id, item) for item in evidence_ids]
        result = {
            "mechanism_citation_id": citation,
            "paper_id": paper_id,
            "title": clean(paper.get("title") or row.get("title")),
            "year": paper.get("year"),
            "path": {
                "material": clip_text(row.get("material"), 500 if full else 260),
                "sensor": clip_text(row.get("sensor"), 500 if full else 260),
                "signal": clip_text(row.get("signal"), 500 if full else 260),
                "system": clip_text(row.get("system"), 500 if full else 260),
            },
            "mechanism_statement" if full else "mechanism_snippet": clip_text(
                row.get("mechanism_statement"), 1000 if full else 480
            ),
            "linked_evidence_ids": linked,
        }
        if row.get("retrieval_score") is not None:
            result["retrieval_score"] = row.get("retrieval_score")
        return result

    def _evidence_record(self, paper_id: str, evidence_id: str, preview: bool) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            select e.paper_id,e.evidence_id,p.title,p.doi,p.year,e.evidence_type,e.evidence_subtype,
                   e.section,e.figure_or_table,e.article_excerpt_text,e.supports_elements_json,
                   e.supports_relations_json,e.raw_json
            from evidence e join papers p using(paper_id)
            where e.paper_id=? and upper(e.evidence_id)=upper(?)
            """,
            (paper_id, evidence_id),
        ).fetchone()
        if row is None:
            return None
        item = {key: row[key] for key in row.keys()}
        location = source_location(item.get("raw_json"))
        citation = self._expose_evidence(paper_id, evidence_id, opened=True)
        result = {
            "citation_id": citation,
            "paper_id": paper_id,
            "title": clean(item.get("title")),
            "year": item.get("year"),
            "evidence_type": clean(item.get("evidence_type")),
            "evidence_subtype": clean(item.get("evidence_subtype")),
            "section": clean(item.get("section") or location.get("section")),
            "page": location.get("page"),
            "figure_or_table": clean(item.get("figure_or_table") or location.get("figure_or_table")),
            "article_excerpt" if not preview else "excerpt_preview": clip_text(
                item.get("article_excerpt_text"), 1800 if not preview else 520
            ),
        }
        if not preview:
            result["supports_elements"] = parse_json(item.get("supports_elements_json"), [])
            result["supports_relations"] = parse_json(item.get("supports_relations_json"), [])
        return result

    def _global_paths(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        rows, _ = self.searcher.ms3(query, max(80, top_k * 20))
        selected: List[Dict[str, Any]] = []
        seen_papers: Set[str] = set()
        for row in rows:
            paper_id = clean(row.get("paper_id"))
            if not paper_id or paper_id in seen_papers or not complete_role_path(row):
                continue
            selected.append(row)
            seen_papers.add(paper_id)
            if len(selected) >= top_k:
                break
        return selected

    def _workspace_paths(self, query: str, paper_ids: Sequence[str], top_k: int) -> List[Dict[str, Any]]:
        allowed = [paper_id for paper_id in paper_ids if paper_id in self.workspace_papers][:8]
        if not allowed:
            return []
        placeholders = ",".join("?" for _ in allowed)
        rows = self.conn.execute(
            f"""
            select m.*,p.title,p.year from mechanisms m join papers p using(paper_id)
            where m.paper_id in ({placeholders})
            """,
            allowed,
        ).fetchall()
        ranked = []
        for raw in rows:
            row = {key: raw[key] for key in raw.keys()}
            if not complete_role_path(row):
                continue
            row["linked_evidence_ids"] = linked_evidence_ids(row.get("evidence_chain_json"))
            ranked.append((overlap_score(query, row), clean(row.get("paper_id")), clean(row.get("mechanism_id")), row))
        ranked.sort(key=lambda value: (-value[0], value[1], value[2]))
        selected: List[Dict[str, Any]] = []
        used_papers: Set[str] = set()
        for _, paper_id, _, row in ranked:
            if paper_id in used_papers:
                continue
            selected.append(row)
            used_papers.add(paper_id)
            if len(selected) >= min(top_k, len(allowed)):
                return selected
        for _, _, _, row in ranked:
            citation = canonical_id(row.get("paper_id"), row.get("mechanism_id"))
            if any(canonical_id(item.get("paper_id"), item.get("mechanism_id")) == citation for item in selected):
                continue
            selected.append(row)
            if len(selected) >= top_k:
                break
        return selected

    def search_ms3(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        query = clean(arguments.get("query")) or self.question
        top_k = min(max(int(arguments.get("top_k") or 6), 1), 8)
        started = __import__("time").perf_counter()
        rows = self._global_paths(query, top_k)
        seconds = __import__("time").perf_counter() - started
        return {
            "scope": "full_frozen_database",
            "query": query,
            "database_counts": self.counts,
            "paths": [self._compact_path(row, full=False) for row in rows],
            "unique_candidate_papers_added": len(rows),
            "workspace_paper_count": len(self.workspace_papers),
            "retrieval_seconds": seconds,
        }

    def trace_paths(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        query = clean(arguments.get("query")) or self.question
        top_k = min(max(int(arguments.get("top_k") or 4), 1), 6)
        raw_papers = arguments.get("paper_ids") or []
        if isinstance(raw_papers, str):
            raw_papers = [raw_papers]
        requested = [clean(item) for item in raw_papers if clean(item)]
        unknown = [item for item in requested if item not in self.workspace_papers]
        rows = self._workspace_paths(query, requested, top_k) if requested else self._global_paths(query, top_k)
        paths = []
        for row in rows:
            path = self._compact_path(row, full=True)
            previews = []
            for evidence_id in row.get("linked_evidence_ids") or linked_evidence_ids(row.get("evidence_chain_json")):
                evidence = self._evidence_record(clean(row.get("paper_id")), evidence_id, preview=True)
                if evidence:
                    previews.append(evidence)
                if len(previews) >= 2:
                    break
            path["linked_evidence_previews"] = previews
            paths.append(path)
        return {
            "scope": "dynamic_workspace" if requested else "full_frozen_database",
            "query": query,
            "requested_paper_ids": requested,
            "unknown_or_unseen_paper_ids": unknown,
            "paths": paths,
            "note": "Each returned path is a stored per-paper Material→Sensor→Signal→System mechanism; multiple papers are returned for cross-paper comparison, not synthesized into an unsupported new path.",
        }

    def inspect_evidence(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        raw_ids = arguments.get("citation_ids") or arguments.get("citation_id") or []
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        requested = [clean(item).upper() for item in raw_ids[:12] if clean(item)]
        evidence = []
        blocked = []
        missing = []
        for citation in requested:
            if citation not in self.exposed_evidence_ids:
                blocked.append(citation)
                continue
            target = self.evidence_targets.get(citation)
            if target is None:
                missing.append(citation)
                continue
            record = self._evidence_record(target[0], target[1], preview=False)
            if record:
                evidence.append(record)
            else:
                missing.append(citation)
        return {
            "evidence": evidence,
            "blocked_unseen_ids": blocked,
            "missing_ids": missing,
            "citation_rule": "Final paper-specific claims may cite only opened paper_id:E# article evidence; mechanism IDs route retrieval but are not final evidence.",
        }

    def call(self, action: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        action = clean(action).lower()
        self.action_counts[action] += 1
        self.action_sequence.append(action)
        if action == "search_ms3":
            result = self.search_ms3(arguments)
        elif action == "trace_paths":
            result = self.trace_paths(arguments)
        elif action == "inspect_evidence":
            result = self.inspect_evidence(arguments)
        else:
            result = {"error": f"Unsupported action {action}", "allowed": list(ALLOWED_ACTIONS)}
        return fit_observation(result, self.max_observation_chars)


def global_agent_protocol(max_tool_calls: int, counts: Dict[str, int]) -> str:
    return (
        "You are a bounded scientific research agent with read-only access to the frozen MS3 materials evidence "
        f"database ({counts['papers']:,} papers, {counts['mechanisms']:,} mechanism objects, "
        f"{counts['evidence']:,} evidence records). You begin with no candidate-paper list. You decide whether and "
        "how to search the full database. No hidden retriever, verifier, reranker, or additional model exists.\n\n"
        "Available actions:\n"
        "1. search_ms3(query, top_k<=8): full-corpus mechanism search returning distinct candidate papers, stored "
        "Material→Sensor→Signal→System paths, and linked evidence IDs.\n"
        "2. trace_paths(query, paper_ids optional, top_k<=6): return full stored paths from multiple papers plus "
        "linked article-evidence previews. If paper_ids are supplied they must already be in the dynamic workspace.\n"
        "3. inspect_evidence(citation_ids<=12): open exact linked paper_id:E# article evidence with provenance and "
        "supported elements/relations. Unseen IDs are blocked.\n"
        f"You may make at most {max_tool_calls} tool calls. For a tool call return one JSON object as "
        "{action:string, arguments:object}. When ready return "
        f"{{action:'final', final:{FINAL_SCHEMA_TEXT}}}.\n\n"
        "Mechanism IDs are routing objects, not final evidence. Every paper-specific final claim must cite at least "
        "one paper_id:E# whose article text was opened by trace_paths or inspect_evidence. Never cite a mechanism ID "
        "as proof. Distinguish demonstrated results from proposals and use INSUFFICIENT_EVIDENCE when the database "
        "does not support a requested claim. Keep the final answer within 300 words, with at most 7 claims, 10 "
        "unique evidence citations, and 10 quantitative facts."
    )


def citation_audit(response: Dict[str, Any], toolbox: GlobalMS3Toolbox) -> Dict[str, Any]:
    citations = canonical_citations(response)
    evidence_citations = [item for item in citations if re.search(r":E\d+$", item, re.I)]
    mechanism_citations = [item for item in citations if item not in evidence_citations]
    valid = [item for item in evidence_citations if item in toolbox.opened_evidence_ids]
    invalid = [item for item in evidence_citations if item not in toolbox.opened_evidence_ids]
    claims = response.get("claims") if isinstance(response.get("claims"), list) else []
    claims_without_opened_evidence = 0
    for claim in claims:
        claim_ids = [clean(item).upper().strip("[]") for item in claim.get("citations", []) if clean(item)]
        if not any(item in toolbox.opened_evidence_ids for item in claim_ids):
            claims_without_opened_evidence += 1
    return {
        "citation_count": len(citations),
        "opened_evidence_citation_count": len(valid),
        "citation_validity": len(valid) / max(1, len(citations)),
        "invalid_or_unopened_evidence_ids": invalid,
        "forbidden_mechanism_or_non_evidence_citations": mechanism_citations,
        "claim_count": len(claims),
        "claims_without_opened_evidence": claims_without_opened_evidence,
        "all_claims_have_opened_article_evidence": bool(claims) and claims_without_opened_evidence == 0,
    }


def run_agent_case(
    case: Dict[str, Any],
    db_path: Path,
    client: ChatClient,
    max_tool_calls: int,
    max_observation_chars: int,
) -> Dict[str, Any]:
    toolbox = GlobalMS3Toolbox(db_path, case["question"], max_observation_chars)
    messages = [
        {"role": "system", "content": global_agent_protocol(max_tool_calls, toolbox.counts)},
        {"role": "user", "content": f"Scientific question:\n{case['question']}"},
    ]
    transcript = []
    try:
        for round_index in range(max_tool_calls):
            parsed, raw, runtime = client.call(messages)
            action = clean(parsed.get("action")).lower()
            turn = {"round": round_index + 1, "model": parsed, "raw_response": raw, "runtime": runtime}
            transcript.append(turn)
            if action == "final" or (not action and clean(parsed.get("answer"))):
                response = normalize_final(parsed)
                break
            arguments = parsed.get("arguments") if isinstance(parsed.get("arguments"), dict) else {}
            observation = toolbox.call(action, arguments)
            turn.update({"tool_action": action, "tool_arguments": arguments, "tool_observation": observation})
            messages.extend(
                [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": "Tool observation:\n" + json.dumps(observation, ensure_ascii=False)},
                ]
            )
        else:
            messages.append(
                {
                    "role": "user",
                    "content": f"Tool limit reached. Return action=final now using exactly: {FINAL_SCHEMA_TEXT}",
                }
            )
            parsed, raw, runtime = client.call(messages)
            transcript.append(
                {"round": max_tool_calls + 1, "forced_final": True, "model": parsed, "raw_response": raw, "runtime": runtime}
            )
            response = normalize_final(parsed)
        return {
            "case_id": case["case_id"],
            "question": case["question"],
            "task_type": case.get("task_type"),
            "coverage_stratum": case.get("coverage_stratum"),
            "method_id": METHOD_ID,
            "response": response,
            "citation_audit": citation_audit(response, toolbox),
            "tool_trace": {
                "tool_calls": sum(toolbox.action_counts.values()),
                "action_counts": dict(toolbox.action_counts),
                "action_sequence": toolbox.action_sequence,
                "global_search_used": bool(toolbox.action_counts.get("search_ms3")),
                "workspace_papers": sorted(toolbox.workspace_papers),
                "opened_evidence_ids": sorted(toolbox.opened_evidence_ids),
            },
            "transcript": transcript,
        }
    finally:
        toolbox.close()


def install_dns_override(host: str, ip_address: str) -> None:
    """Pin an API hostname to a reachable address while retaining TLS SNI."""
    original = socket.getaddrinfo

    def getaddrinfo(name: str, port: Any, *args: Any, **kwargs: Any) -> Any:
        return original(ip_address if name == host else name, port, *args, **kwargs)

    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]


def load_cases(
    path: Path,
    offset: int,
    limit: int,
    coverage_filter: str = "all",
    stratified_per_group: int = 0,
) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("cases", []) if isinstance(data, dict) else data
    result = []
    for index, row in enumerate(rows, 1):
        question = clean(row.get("question") or row.get("query"))
        if not question:
            continue
        result.append(
            {
                **row,
                "case_id": clean(row.get("case_id")) or f"case_{index:04d}",
                "question": question,
            }
        )
    if coverage_filter != "all":
        result = [row for row in result if clean(row.get("coverage_stratum")) == coverage_filter]
    if stratified_per_group:
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for row in result:
            key = (clean(row.get("task_type")), clean(row.get("task_bucket")))
            grouped.setdefault(key, []).append(row)
        result = [
            row
            for key in sorted(grouped)
            for row in grouped[key][:stratified_per_group]
        ]
    stop = offset + limit if limit else None
    return result[offset:stop]


def run_tool_smoke(db_path: Path, query: str, output_dir: Path, max_observation_chars: int) -> Dict[str, Any]:
    toolbox = GlobalMS3Toolbox(db_path, query, max_observation_chars)
    try:
        search = toolbox.call("search_ms3", {"query": query, "top_k": 4})
        paper_ids = [item["paper_id"] for item in search.get("paths", [])[:2]]
        trace = toolbox.call("trace_paths", {"query": query, "paper_ids": paper_ids, "top_k": 2})
        evidence_ids = []
        for path in trace.get("paths", []):
            evidence_ids.extend(item["citation_id"] for item in path.get("linked_evidence_previews", []))
        inspect = toolbox.call("inspect_evidence", {"citation_ids": evidence_ids[:4]})
        result = {
            "status": "tool_smoke_complete",
            "query": query,
            "database_counts": toolbox.counts,
            "search_ms3": search,
            "trace_paths": trace,
            "inspect_evidence": inspect,
            "action_sequence": toolbox.action_sequence,
            "opened_evidence_ids": sorted(toolbox.opened_evidence_ids),
        }
        write_json(output_dir / "tool_smoke.json", result)
        return result
    finally:
        toolbox.close()


def summarize(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    healthy = [row for row in records if not row.get("error")]
    audits = [row["citation_audit"] for row in healthy]
    traces = [row["tool_trace"] for row in healthy]
    return {
        "case_count": len(records),
        "healthy_case_count": len(healthy),
        "global_search_use_rate": statistics.fmean(float(row["global_search_used"]) for row in traces) if traces else None,
        "mean_tool_calls": statistics.fmean(row["tool_calls"] for row in traces) if traces else None,
        "mean_workspace_papers": statistics.fmean(len(row["workspace_papers"]) for row in traces) if traces else None,
        "mean_citation_validity": statistics.fmean(row["citation_validity"] for row in audits) if audits else None,
        "all_claims_evidence_grounded_rate": (
            statistics.fmean(float(row["all_claims_have_opened_article_evidence"]) for row in audits) if audits else None
        ),
        "total_forbidden_mechanism_citations": sum(len(row["forbidden_mechanism_or_non_evidence_citations"]) for row in audits),
        "action_counts": dict(sum((Counter(row["action_counts"]) for row in traces), Counter())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--tool-smoke-query")
    parser.add_argument("--model")
    parser.add_argument("--api-base")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--compatibility", choices=("deepseek", "openai"), default="openai")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--coverage-filter",
        choices=("all", "covered", "partially_covered", "out_of_domain"),
        default="all",
    )
    parser.add_argument("--stratified-per-group", type=int, default=0)
    parser.add_argument("--api-resolve-host", default="api.deepseek.com")
    parser.add_argument("--api-resolve-ip", default="")
    parser.add_argument("--max-tool-calls", type=int, default=6)
    parser.add_argument("--max-observation-chars", type=int, default=18000)
    parser.add_argument("--max-output-tokens", type=int, default=1800)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.db.is_file():
        raise FileNotFoundError(args.db)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.tool_smoke_query:
        result = run_tool_smoke(args.db, args.tool_smoke_query, args.output_dir, args.max_observation_chars)
        print(json.dumps({"status": result["status"], "database_counts": result["database_counts"]}, indent=2))
        return 0
    if not args.questions or not args.questions.is_file():
        raise ValueError("--questions is required unless --tool-smoke-query is used")
    if not args.model or not args.api_base:
        raise ValueError("--model and --api-base are required for agent runs")

    if args.api_resolve_ip:
        install_dns_override(args.api_resolve_host, args.api_resolve_ip)
    cases = load_cases(
        args.questions,
        args.offset,
        args.limit,
        args.coverage_filter,
        args.stratified_per_group,
    )
    if not cases:
        raise RuntimeError("No cases selected")
    api_key = clean(os.environ.get(args.api_key_env))
    if not api_key and args.compatibility == "openai" and args.api_base.startswith("http://"):
        api_key = "local-not-secret"
    if not api_key:
        raise RuntimeError(f"Missing API key environment variable: {args.api_key_env}")
    client = ChatClient(
        args.api_base, api_key, args.model, args.compatibility, args.max_output_tokens, args.timeout, args.retries
    )
    run_config = {
        "experiment_id": "ms3_fig4_global_agent_v2",
        "method_id": METHOD_ID,
        "database_file": args.db.name,
        "database_size": args.db.stat().st_size,
        "database_mtime_ns": args.db.stat().st_mtime_ns,
        "questions_sha256": file_sha256(args.questions),
        "model": args.model,
        "api_base": args.api_base,
        "compatibility": args.compatibility,
        "max_tool_calls": args.max_tool_calls,
        "max_observation_chars": args.max_observation_chars,
        "coverage_filter": args.coverage_filter,
        "stratified_per_group": args.stratified_per_group or None,
        "api_resolve_host": args.api_resolve_host if args.api_resolve_ip else None,
        "api_resolve_ip": args.api_resolve_ip or None,
        "temperature": 0,
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "tool_actions": list(ALLOWED_ACTIONS),
        "initial_candidate_papers": 0,
        "search_scope": "full_frozen_database",
        "final_evidence_rule": "opened paper_id:E# article evidence only",
    }
    run_signature = sha256_json(run_config)
    record_dir = args.output_dir / "records"
    record_dir.mkdir(exist_ok=True)

    def task(case: Dict[str, Any]) -> Dict[str, Any]:
        cache = record_dir / f"{case['case_id']}.json"
        if cache.exists() and not args.force:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if saved.get("run_signature") == run_signature and not saved.get("error"):
                return saved
        try:
            record = run_agent_case(case, args.db, client, args.max_tool_calls, args.max_observation_chars)
        except Exception as error:  # noqa: BLE001
            record = {
                "case_id": case["case_id"],
                "question": case["question"],
                "method_id": METHOD_ID,
                "error": repr(error),
            }
        record["run_signature"] = run_signature
        write_json(cache, record)
        return record

    completed: Dict[str, Dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(task, case): case for case in cases}
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            case = futures[future]
            record = future.result()
            completed[case["case_id"]] = record
            ordered = [completed[row["case_id"]] for row in cases if row["case_id"] in completed]
            with WRITE_LOCK:
                write_json(
                    args.output_dir / "results.partial.json",
                    {
                        "status": "running",
                        "run_config": run_config,
                        "completed": len(ordered),
                        "expected": len(cases),
                        "records": ordered,
                    },
                )
            print(
                f"[global-agent {index}/{len(cases)}] {case['case_id']} "
                f"status={'ERROR' if record.get('error') else record['response']['conclusion']}",
                flush=True,
            )

    records = [completed[case["case_id"]] for case in cases]
    summary = summarize(records)
    output = {
        "status": "complete" if summary["healthy_case_count"] == len(records) else "complete_with_errors",
        "run_config": run_config,
        "run_signature": run_signature,
        "summary": summary,
        "records": records,
    }
    write_json(args.output_dir / "results.json", output)
    write_json(args.output_dir / "summary.json", summary)
    print(json.dumps({"status": output["status"], "summary": summary}, ensure_ascii=False, indent=2))
    return 0 if output["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
