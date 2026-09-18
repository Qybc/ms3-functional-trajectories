#!/usr/bin/env python3
"""Run one controller across five frozen MS3 evidence-access conditions.

The runner is intentionally self-contained and dependency-light. Retrieval and
tool execution are deterministic; only the named controller generates search
actions and final answers. Case-condition records are cached independently so a
terminated process can resume without repeating successful model calls.

The filename and experiment identifiers predate the final manuscript figure
order and are retained so archived run manifests remain interpretable.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import csv
import hashlib
import json
import math
import os
import random
import re
import sqlite3
import statistics
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


METHODS = ("direct", "text_rag", "ms3_rag", "text_agent", "ms3_agent")
PATH_FIELDS = ("material", "sensor", "signal", "system")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[.\-/][A-Za-z0-9]+)*|[\u4e00-\u9fff]")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from", "how", "in",
    "into", "is", "it", "of", "on", "or", "paper", "reported", "study", "that", "the", "their", "this",
    "to", "using", "was", "were", "what", "which", "with",
}
CONCLUSIONS = {"SUPPORTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE"}
DEFAULT_PDF_ROOTS = tuple(
    Path(value)
    for value in os.environ.get("MS3_PDF_ROOTS", "").split(os.pathsep)
    if value
)
WRITE_LOCK = threading.Lock()


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def parse_json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {"answer": text, "parse_warning": "non-object JSON"}
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", text):
            try:
                value, _ = decoder.raw_decode(text[match.start() :])
                if isinstance(value, dict) and ({"action", "answer", "conclusion"} & set(value)):
                    value.setdefault("parse_warning", "recovered JSON object from surrounding text")
                    return value
            except json.JSONDecodeError:
                continue
    return {"answer": text, "parse_warning": "model response was not valid JSON"}


def tokenize(text: str) -> list[str]:
    return [token for token in (item.lower() for item in TOKEN_PATTERN.findall(text or "")) if token not in STOPWORDS]


def bm25(question: str, records: list[dict[str, Any]], field: str = "search_text") -> list[dict[str, Any]]:
    if not records:
        return []
    query = collections.Counter(tokenize(question))
    documents = [tokenize(clean(record.get(field))) for record in records]
    lengths = [len(document) for document in documents]
    average_length = statistics.fmean(lengths) if lengths else 1.0
    document_frequency: collections.Counter[str] = collections.Counter()
    for document in documents:
        document_frequency.update(set(document))
    count = len(documents)
    scored = []
    for record, document, length in zip(records, documents, lengths):
        frequencies = collections.Counter(document)
        score = 0.0
        for term, query_frequency in query.items():
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            inverse = math.log(1 + (count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * length / max(average_length, 1.0))
            score += query_frequency * inverse * frequency * 2.5 / denominator
        item = dict(record)
        item["retrieval_score"] = round(score, 6)
        scored.append(item)
    return sorted(scored, key=lambda row: (-row["retrieval_score"], clean(row.get("citation_id"))))


def normalized_title(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", clean(text).lower()))


def named_paper_ids(question: str, papers: list[dict[str, Any]]) -> list[str]:
    normalized_question = normalized_title(question)
    return [
        clean(paper.get("paper_id"))
        for paper in papers
        if len(normalized_title(paper.get("title"))) >= 20
        and normalized_title(paper.get("title")) in normalized_question
    ]


def extract_pdf_pages(pdf_path: Path) -> tuple[list[str], str]:
    errors = []
    try:
        from pypdf import PdfReader

        pages = [clean(page.extract_text() or "") for page in PdfReader(str(pdf_path)).pages]
        if any(pages):
            return pages, "pypdf"
        errors.append("pypdf returned no text")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pypdf: {exc!r}")
    try:
        import fitz

        with fitz.open(pdf_path) as document:
            pages = [clean(page.get_text("text")) for page in document]
        if any(pages):
            return pages, "pymupdf"
        errors.append("pymupdf returned no text")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pymupdf: {exc!r}")
    try:
        with tempfile.NamedTemporaryFile(suffix=".txt") as handle:
            subprocess.run(["pdftotext", "-layout", str(pdf_path), handle.name], check=True, capture_output=True)
            pages = [clean(page) for page in Path(handle.name).read_text(encoding="utf-8", errors="ignore").split("\f")]
        if any(pages):
            return pages, "pdftotext"
        errors.append("pdftotext returned no text")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pdftotext: {exc!r}")
    raise RuntimeError(f"Could not extract {pdf_path}: {'; '.join(errors)}")


def chunk_pages(
    pages: list[str], paper: dict[str, Any], chunk_words: int, overlap_words: int
) -> list[dict[str, Any]]:
    chunks = []
    step = chunk_words - overlap_words
    for page_number, page in enumerate(pages, 1):
        words = clean(page).split()
        for start in range(0, len(words), step):
            window = words[start : start + chunk_words]
            if not window or (start and len(window) <= overlap_words):
                break
            chunk_id = f"R{len(chunks) + 1:04d}"
            citation_id = f"{paper['paper_id']}:{chunk_id}"
            text = " ".join(window)
            chunks.append(
                {
                    "citation_id": citation_id,
                    "paper_id": paper["paper_id"],
                    "title": clean(paper.get("title")),
                    "doi": clean(paper.get("doi")),
                    "page": page_number,
                    "chunk_id": chunk_id,
                    "text": text,
                    "search_text": f"{paper.get('title', '')} {text}",
                }
            )
            if start + chunk_words >= len(words):
                break
    return chunks


def resolve_pdf(paper: dict[str, Any], pdf_roots: list[Path]) -> Path:
    stored = clean(paper.get("pdf_path"))
    candidates = [Path(stored).expanduser()] if stored else []
    doi_name = clean(paper.get("doi")).replace("/", "_") + ".pdf"
    if doi_name != ".pdf":
        candidates.extend(root.expanduser() / doi_name for root in pdf_roots)
    found = next((candidate for candidate in candidates if candidate.is_file()), None)
    if found is None:
        raise FileNotFoundError(f"PDF unavailable; attempted {[str(item) for item in candidates]}")
    return found


def load_or_build_chunks(
    paper: dict[str, Any], cache_dir: Path, pdf_roots: list[Path], chunk_words: int, overlap_words: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pdf_path = resolve_pdf(paper, pdf_roots)
    stat = pdf_path.stat()
    signature = {
        "file": pdf_path.name,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "chunk_words": chunk_words,
        "overlap_words": overlap_words,
    }
    cache = cache_dir / f"{paper['paper_id']}.json"
    if cache.exists():
        saved = load_json(cache)
        if saved.get("signature") == signature:
            return saved["chunks"], saved["extraction"]
    pages, backend = extract_pdf_pages(pdf_path)
    chunks = chunk_pages(pages, paper, chunk_words, overlap_words)
    extraction = {
        "pdf_file": pdf_path.name,
        "backend": backend,
        "pages": len(pages),
        "chunks": len(chunks),
    }
    write_json(cache, {"signature": signature, "extraction": extraction, "chunks": chunks})
    return chunks, extraction


def db_rows(conn: sqlite3.Connection, query: str, params: list[Any]) -> list[dict[str, Any]]:
    return [{key: row[key] for key in row.keys()} for row in conn.execute(query, params).fetchall()]


def source_location(raw_json: Any) -> dict[str, Any]:
    raw = parse_json(raw_json, {})
    source = raw.get("source", {}) if isinstance(raw, dict) else {}
    return {
        "page": source.get("page") or source.get("page_number") or source.get("pdf_page"),
        "section": clean(source.get("section")),
        "figure_or_table": clean(source.get("figure_or_table")),
    }


def evidence_ids(value: Any) -> list[str]:
    found = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        else:
            for match in re.findall(r"\bE\d+\b", clean(item), re.I):
                if match.upper() not in found:
                    found.append(match.upper())

    walk(parse_json(value, value))
    return found


def prepare_resources(
    case: dict[str, Any], db_path: Path, cache_dir: Path, pdf_roots: list[Path], chunk_words: int, overlap_words: int
) -> dict[str, Any]:
    candidate_ids = [clean(item) for item in case.get("retrieved_paper_ids", [])[:4] if clean(item)]
    placeholders = ",".join("?" for _ in candidate_ids)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        papers_unordered = db_rows(
            conn,
            f"select paper_id,doi,title,year,pdf_path from papers where paper_id in ({placeholders})",
            candidate_ids,
        )
        paper_by_id = {row["paper_id"]: row for row in papers_unordered}
        papers = [paper_by_id[item] for item in candidate_ids if item in paper_by_id]
        raw_mechanisms = db_rows(
            conn,
            f"select m.*,p.title,p.doi,p.year from mechanisms m join papers p using(paper_id) "
            f"where m.paper_id in ({placeholders}) order by m.paper_id,m.mechanism_id",
            candidate_ids,
        )
        raw_evidence = db_rows(
            conn,
            f"select e.*,p.title,p.doi,p.year from evidence e join papers p using(paper_id) "
            f"where e.paper_id in ({placeholders}) order by e.paper_id,e.evidence_id",
            candidate_ids,
        )
    finally:
        conn.close()

    mechanisms = []
    for row in raw_mechanisms:
        citation_id = f"{row['paper_id']}:{clean(row.get('mechanism_id')).upper()}"
        path = {field: clean(row.get(field)) for field in PATH_FIELDS}
        mechanisms.append(
            {
                "citation_id": citation_id,
                "paper_id": row["paper_id"],
                "mechanism_id": clean(row.get("mechanism_id")).upper(),
                "title": clean(row.get("title")),
                "doi": clean(row.get("doi")),
                "mechanism_statement": clean(row.get("mechanism_statement")),
                "ms3_path": path,
                "linked_evidence_ids": evidence_ids(row.get("evidence_chain_json")),
                "search_text": " ".join(
                    [clean(row.get("title")), clean(row.get("task")), clean(row.get("mechanism_statement")), *path.values()]
                ),
            }
        )
    evidence = []
    for row in raw_evidence:
        location = source_location(row.get("raw_json"))
        citation_id = f"{row['paper_id']}:{clean(row.get('evidence_id')).upper()}"
        evidence.append(
            {
                "citation_id": citation_id,
                "paper_id": row["paper_id"],
                "evidence_id": clean(row.get("evidence_id")).upper(),
                "title": clean(row.get("title")),
                "doi": clean(row.get("doi")),
                "evidence_type": clean(row.get("evidence_type")),
                "evidence_subtype": clean(row.get("evidence_subtype")),
                "section": clean(row.get("section") or location.get("section")),
                "page": location.get("page"),
                "figure_or_table": clean(row.get("figure_or_table") or location.get("figure_or_table")),
                "article_excerpt": clean(row.get("article_excerpt_text")),
                "supports_elements": parse_json(row.get("supports_elements_json"), []),
                "supports_relations": parse_json(row.get("supports_relations_json"), []),
                "search_text": " ".join(
                    [
                        clean(row.get("title")), clean(row.get("evidence_type")), clean(row.get("evidence_subtype")),
                        clean(row.get("section")), clean(row.get("article_excerpt_text")),
                        clean(row.get("supports_elements_json")), clean(row.get("supports_relations_json")),
                    ]
                ),
            }
        )

    # The plain-text control uses the exact same frozen source excerpts as MS3,
    # stripped of evidence labels, supported relations, and mechanism objects.
    # This avoids confounding the structural comparison with incomplete PDFs.
    chunks = [
        {
            "citation_id": row["citation_id"],
            "paper_id": row["paper_id"],
            "title": row["title"],
            "doi": row["doi"],
            "page": row["page"],
            "section": row["section"],
            "figure_or_table": row["figure_or_table"],
            "text": row["article_excerpt"],
            "search_text": f"{row['title']} {row['section']} {row['article_excerpt']}",
        }
        for row in evidence
        if clean(row.get("article_excerpt"))
    ]
    extractions = [{"source": "matched de-structured article excerpts", "excerpt_count": len(chunks)}]
    extraction_failures: list[dict[str, Any]] = []
    return {
        "case_id": case["case_id"],
        "question": case["question"],
        "candidate_paper_ids": candidate_ids,
        "papers": papers,
        "named_paper_ids": named_paper_ids(case["question"], papers),
        "raw_chunks": chunks,
        "mechanisms": mechanisms,
        "evidence": evidence,
        "extractions": extractions,
        "extraction_failures": extraction_failures,
        "resource_counts": {
            "papers": len(papers), "text_excerpts": len(chunks), "mechanisms": len(mechanisms), "evidence": len(evidence)
        },
    }


def compact_chunk(row: dict[str, Any], full: bool = True) -> dict[str, Any]:
    value = {
        key: row.get(key)
        for key in ("citation_id", "paper_id", "title", "section", "page", "figure_or_table")
    }
    value["article_excerpt" if full else "snippet"] = clean(row.get("text")) if full else clean(row.get("text"))[:420]
    if "retrieval_score" in row:
        value["retrieval_score"] = row["retrieval_score"]
    return value


def compact_mechanism(row: dict[str, Any], full: bool = True) -> dict[str, Any]:
    value = {key: row.get(key) for key in ("citation_id", "paper_id", "mechanism_id", "title")}
    value["mechanism_statement" if full else "snippet"] = (
        clean(row.get("mechanism_statement")) if full else clean(row.get("mechanism_statement"))[:420]
    )
    if full:
        value["ms3_path"] = row.get("ms3_path")
        value["linked_evidence_ids"] = row.get("linked_evidence_ids")
    if "retrieval_score" in row:
        value["retrieval_score"] = row["retrieval_score"]
    return value


def compact_evidence(row: dict[str, Any], full: bool = True) -> dict[str, Any]:
    keys = ("citation_id", "paper_id", "evidence_id", "title", "evidence_type", "evidence_subtype", "section", "page", "figure_or_table")
    value = {key: row.get(key) for key in keys}
    value["article_excerpt" if full else "snippet"] = (
        clean(row.get("article_excerpt")) if full else clean(row.get("article_excerpt"))[:420]
    )
    if full:
        value["supports_elements"] = row.get("supports_elements")
        value["supports_relations"] = row.get("supports_relations")
    if "retrieval_score" in row:
        value["retrieval_score"] = row["retrieval_score"]
    return value


def fit_records(records: list[dict[str, Any]], max_chars: int, max_items: int) -> list[dict[str, Any]]:
    selected = []
    used = 2
    for record in records:
        size = len(json.dumps(record, ensure_ascii=False)) + 1
        if selected and used + size > max_chars:
            continue
        selected.append(record)
        used += size
        if len(selected) >= max_items:
            break
    return selected


def apply_named_paper_quota(
    ranked: list[dict[str, Any]], named_papers: list[str], per_paper: int
) -> list[dict[str, Any]]:
    """Put a fixed number from each explicitly named paper first."""
    if not named_papers:
        return ranked
    prioritized = []
    seen = set()
    for paper_id in named_papers:
        for row in [item for item in ranked if item.get("paper_id") == paper_id][:per_paper]:
            citation = clean(row.get("citation_id")).upper()
            if citation not in seen:
                prioritized.append(row)
                seen.add(citation)
    prioritized.extend(row for row in ranked if clean(row.get("citation_id")).upper() not in seen)
    return prioritized


def select_text_context(resources: dict[str, Any], max_chars: int) -> tuple[list[dict[str, Any]], set[str]]:
    ranked = bm25(resources["question"], resources["raw_chunks"])
    named = resources["named_paper_ids"]
    ranked = apply_named_paper_quota(ranked, named, 10 if len(named) == 1 else 6)
    records = fit_records([compact_chunk(row) for row in ranked], max_chars, 16)
    return records, {clean(row["citation_id"]).upper() for row in records}


def select_ms3_context(resources: dict[str, Any], max_chars: int) -> tuple[dict[str, Any], set[str]]:
    named = resources["named_paper_ids"]
    mechanisms = bm25(resources["question"], resources["mechanisms"])
    evidence = bm25(resources["question"], resources["evidence"])
    mechanisms = apply_named_paper_quota(mechanisms, named, 4 if len(named) == 1 else 3)
    selected_mechanisms = [compact_mechanism(row) for row in mechanisms[:8]]
    linked = {
        f"{row['paper_id']}:{evidence_id}".upper()
        for row in mechanisms[:8]
        for evidence_id in row.get("linked_evidence_ids", [])
    }
    evidence.sort(key=lambda row: (row["citation_id"].upper() not in linked, -row["retrieval_score"], row["citation_id"]))
    evidence = apply_named_paper_quota(evidence, named, 10 if len(named) == 1 else 6)
    mechanism_chars = len(json.dumps(selected_mechanisms, ensure_ascii=False))
    selected_evidence = fit_records(
        [compact_evidence(row) for row in evidence], max(3000, max_chars - mechanism_chars), 20
    )
    context = {
        "candidate_papers": [
            {key: paper.get(key) for key in ("paper_id", "doi", "title", "year")} for paper in resources["papers"]
        ],
        "mechanism_objects": selected_mechanisms,
        "evidence_items": selected_evidence,
    }
    valid = {
        clean(row["citation_id"]).upper() for row in [*selected_mechanisms, *selected_evidence]
    }
    return context, valid


FINAL_SCHEMA_TEXT = (
    "{answer:string, conclusion:SUPPORTED|PARTIALLY_SUPPORTED|INSUFFICIENT_EVIDENCE, "
    "claims:[{claim:string,citations:[string]}], evidence_citations:[string], quantitative_facts:[string]}"
)


def final_system(access_rule: str) -> str:
    return (
        "You answer scientific questions about conductive-fiber and flexible-sensor papers. "
        f"{access_rule} Return valid JSON only using exactly this schema: {FINAL_SCHEMA_TEXT}. "
        "Do not invent facts, measurements, units, experiments, applications, or citation IDs. Distinguish actual "
        "demonstrations from proposals. Every paper-specific claim must cite an identifier that was visible in the "
        "provided context or tool observations. If support is incomplete, state the gap and abstain at the claim level."
        " Be concise: keep the answer within 250 words and return at most 6 claims, 8 unique citations, and 8 "
        "quantitative facts. Do not enumerate unrelated applications."
    )


class ChatClient:
    def __init__(
        self, api_base: str, api_key: str, model: str, compatibility: str, max_tokens: int, timeout: int, retries: int
    ) -> None:
        self.endpoint = api_base.rstrip("/")
        if not self.endpoint.endswith("/chat/completions"):
            self.endpoint += "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.compatibility = compatibility
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.retries = retries

    def call(self, messages: list[dict[str, str]]) -> tuple[dict[str, Any], str, dict[str, Any]]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "stream": False,
        }
        if self.compatibility == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            started = time.time()
            request = urllib.request.Request(
                self.endpoint,
                data=encoded,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8", "ignore")
                    request_id = response.headers.get("x-request-id")
                data = json.loads(raw)
                choice = data["choices"][0]
                content = clean(choice["message"].get("content"))
                if not content:
                    raise RuntimeError(f"Empty model content: {raw[:500]}")
                parsed_content = parse_json_object(content)
                finish_reason = choice.get("finish_reason")
                if finish_reason == "length":
                    parsed_content["parse_warning"] = "model output was truncated at max_tokens"
                runtime = {
                    "seconds": round(time.time() - started, 3),
                    "usage": data.get("usage", {}),
                    "request_id": request_id,
                    "attempt": attempt + 1,
                    "finish_reason": finish_reason,
                }
                return parsed_content, content, runtime
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, KeyError, RuntimeError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(min(2**attempt, 12))
        raise RuntimeError(f"Model request failed after {self.retries + 1} attempts: {last_error!r}")


def normalize_final(value: dict[str, Any]) -> dict[str, Any]:
    if clean(value.get("action")).lower() == "final":
        if isinstance(value.get("final"), dict):
            value = value["final"]
        elif isinstance(value.get("arguments"), dict):
            arguments = value["arguments"]
            value = arguments.get("final") if isinstance(arguments.get("final"), dict) else arguments
    conclusion = clean(value.get("conclusion")).upper()
    if conclusion not in CONCLUSIONS:
        conclusion = "INSUFFICIENT_EVIDENCE" if not clean(value.get("answer")) else "PARTIALLY_SUPPORTED"
    claims = value.get("claims") if isinstance(value.get("claims"), list) else []
    normalized_claims = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        citations = claim.get("citations") if isinstance(claim.get("citations"), list) else []
        normalized_claims.append({"claim": clean(claim.get("claim")), "citations": [clean(item) for item in citations if clean(item)]})
    citations = value.get("evidence_citations") if isinstance(value.get("evidence_citations"), list) else []
    facts = value.get("quantitative_facts") if isinstance(value.get("quantitative_facts"), list) else []
    result = {
        "answer": clean(value.get("answer")),
        "conclusion": conclusion,
        "claims": normalized_claims,
        "evidence_citations": [clean(item) for item in citations if clean(item)],
        "quantitative_facts": [clean(item) for item in facts if clean(item)],
    }
    if value.get("parse_warning"):
        result["parse_warning"] = value["parse_warning"]
    return result


def canonical_citations(response: dict[str, Any]) -> list[str]:
    values = list(response.get("evidence_citations") or [])
    for claim in response.get("claims") or []:
        values.extend(claim.get("citations") or [])
    return list(dict.fromkeys(clean(item).upper().strip("[]") for item in values if clean(item)))


class ToolBox:
    def __init__(self, resources: dict[str, Any], kind: str, max_observation_chars: int) -> None:
        self.resources = resources
        self.kind = kind
        self.max_observation_chars = max_observation_chars
        self.exposed_ids: set[str] = set()
        self.exposed_paper_ids: set[str] = set()
        self.text_by_id = {row["citation_id"].upper(): row for row in resources["raw_chunks"]}
        self.mechanism_by_id = {row["citation_id"].upper(): row for row in resources["mechanisms"]}
        self.evidence_by_id = {row["citation_id"].upper(): row for row in resources["evidence"]}

    def _record(self, records: list[dict[str, Any]]) -> None:
        for row in records:
            citation = clean(row.get("citation_id")).upper()
            paper_id = clean(row.get("paper_id"))
            if citation:
                self.exposed_ids.add(citation)
            if paper_id:
                self.exposed_paper_ids.add(paper_id)

    def _record_visible(self, value: Any) -> None:
        if isinstance(value, dict):
            if value.get("citation_id"):
                self._record([value])
            for child in value.values():
                self._record_visible(child)
        elif isinstance(value, list):
            for child in value:
                self._record_visible(child)

    def _clip(self, value: Any) -> Any:
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded) <= self.max_observation_chars:
            return value
        if isinstance(value, dict):
            for key in ("results", "records", "mechanisms", "evidence"):
                if isinstance(value.get(key), list):
                    trimmed = dict(value)
                    records = []
                    for record in value[key]:
                        candidate = {**trimmed, key: [*records, record]}
                        if len(json.dumps(candidate, ensure_ascii=False)) > self.max_observation_chars:
                            break
                        records.append(record)
                    trimmed[key] = records
                    trimmed["truncated"] = len(records) < len(value[key])
                    return trimmed
        return {"warning": "observation exceeded ceiling", "snippet": encoded[: self.max_observation_chars - 100]}

    def call(self, action: str, arguments: dict[str, Any]) -> Any:
        action = clean(action).lower()
        if self.kind == "text":
            result = self._call_text(action, arguments)
        else:
            result = self._call_ms3(action, arguments)
        visible = self._clip(result)
        self._record_visible(visible)
        return visible

    def _call_text(self, action: str, arguments: dict[str, Any]) -> Any:
        if action == "search_text":
            query = clean(arguments.get("query")) or self.resources["question"]
            top_k = min(max(int(arguments.get("top_k") or 6), 1), 8)
            rows = bm25(query, self.resources["raw_chunks"])[:top_k]
            return {"query": query, "results": [compact_chunk(row, full=False) for row in rows]}
        if action == "inspect_text":
            ids = arguments.get("citation_ids") or arguments.get("citation_id") or []
            if isinstance(ids, str):
                ids = [ids]
            rows = [self.text_by_id[item.upper()] for item in ids[:8] if item.upper() in self.text_by_id]
            return {"records": [compact_chunk(row, full=True) for row in rows], "unknown_ids": [item for item in ids[:8] if item.upper() not in self.text_by_id]}
        return {"error": f"Unsupported text action {action}", "allowed": ["search_text", "inspect_text", "final"]}

    def _call_ms3(self, action: str, arguments: dict[str, Any]) -> Any:
        if action == "search_ms3":
            query = clean(arguments.get("query")) or self.resources["question"]
            top_k = min(max(int(arguments.get("top_k") or 6), 1), 8)
            mechanisms = bm25(query, self.resources["mechanisms"])[:top_k]
            evidence = bm25(query, self.resources["evidence"])[:top_k]
            return {
                "query": query,
                "mechanisms": [compact_mechanism(row, full=False) for row in mechanisms],
                "evidence": [compact_evidence(row, full=False) for row in evidence],
            }
        if action == "inspect_ms3":
            ids = arguments.get("citation_ids") or arguments.get("citation_id") or []
            if isinstance(ids, str):
                ids = [ids]
            mechanisms = [self.mechanism_by_id[item.upper()] for item in ids[:10] if item.upper() in self.mechanism_by_id]
            evidence = [self.evidence_by_id[item.upper()] for item in ids[:10] if item.upper() in self.evidence_by_id]
            known = set(self.mechanism_by_id) | set(self.evidence_by_id)
            return {
                "mechanisms": [compact_mechanism(row) for row in mechanisms],
                "evidence": [compact_evidence(row) for row in evidence],
                "unknown_ids": [item for item in ids[:10] if item.upper() not in known],
            }
        if action == "trace_path":
            paper_id = clean(arguments.get("paper_id"))
            query = clean(arguments.get("query")) or self.resources["question"]
            candidates = [row for row in self.resources["mechanisms"] if not paper_id or row["paper_id"] == paper_id]
            rows = bm25(query, candidates)[:3]
            linked_ids = [
                f"{row['paper_id']}:{evidence_id}".upper()
                for row in rows
                for evidence_id in row.get("linked_evidence_ids", [])
            ]
            linked = [self.evidence_by_id[item] for item in linked_ids[:12] if item in self.evidence_by_id]
            return {
                "mechanisms": [compact_mechanism(row) for row in rows],
                "linked_evidence": [compact_evidence(row) for row in linked],
            }
        return {"error": f"Unsupported MS3 action {action}", "allowed": ["search_ms3", "inspect_ms3", "trace_path", "final"]}


def run_static(
    case: dict[str, Any], method: str, resources: dict[str, Any], client: ChatClient, max_context_chars: int
) -> tuple[dict[str, Any], list[dict[str, Any]], set[str], set[str], dict[str, Any]]:
    question = case["question"]
    if method == "direct":
        context = None
        valid_ids: set[str] = set()
        exposed_papers: set[str] = set()
        rule = "No retrieval or external knowledge source is available; do not fabricate citations."
        user = f"Question:\n{question}\n\nNo external context is available."
    elif method == "text_rag":
        context, valid_ids = select_text_context(resources, max_context_chars)
        exposed_papers = {item["paper_id"] for item in context}
        rule = (
            "Use only the supplied de-structured article excerpts for paper-specific claims. "
            "Cite exactly as paper_id:E#. No MS3 labels, relations, paths, or mechanism objects are available."
        )
        user = f"Question:\n{question}\n\nArticle excerpts:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    else:
        context, valid_ids = select_ms3_context(resources, max_context_chars)
        exposed_papers = {
            item["paper_id"] for item in [*context["mechanism_objects"], *context["evidence_items"]]
        }
        rule = (
            "Use only the supplied MS3 records for paper-specific claims. Cite exactly as paper_id:E# for evidence "
            "or paper_id:mechanism_id (for example paper_id:MO_001) for mechanism objects."
        )
        user = f"Question:\n{question}\n\nMS3 structured records:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    messages = [{"role": "system", "content": final_system(rule)}, {"role": "user", "content": user}]
    parsed, raw, runtime = client.call(messages)
    return normalize_final(parsed), [{"raw_response": raw, "runtime": runtime}], valid_ids, exposed_papers, {"context": context}


def agent_protocol(kind: str, max_rounds: int) -> str:
    if kind == "text":
        actions = (
            "search_text(query, top_k<=8): returns ranked de-structured article-excerpt snippets; "
            "inspect_text(citation_ids<=8): returns complete selected excerpts"
        )
        citation = "paper_id:E#"
    else:
        actions = (
            "search_ms3(query, top_k<=8): searches mechanism and evidence records; "
            "inspect_ms3(citation_ids<=10): opens exact records; "
            "trace_path(paper_id, query): returns a ranked MS3 path and its linked evidence"
        )
        citation = "paper_id:E# or paper_id:mechanism_id (for example paper_id:MO_001)"
    return (
        "You are a bounded scientific research agent. A deterministic, paper-scoped tool is available, but you decide "
        "whether and how to call it. No other retrieval or model exists. "
        f"Available actions: {actions}. You may make at most {max_rounds} tool calls. Return one JSON object per turn. "
        "For a tool call use {action:string, arguments:object}. When ready use "
        f"{{action:'final', final:{FINAL_SCHEMA_TEXT}}}. Cite only identifiers observed from tools as {citation}. "
        "Do not invent facts or identifiers; distinguish demonstrated results from proposed applications; explicitly "
        "report insufficient evidence. The final answer must be within 250 words and contain at most 6 claims, 8 "
        "unique citations, and 8 quantitative facts; do not enumerate unrelated applications."
    )


def run_agent(
    case: dict[str, Any], kind: str, resources: dict[str, Any], client: ChatClient, max_rounds: int, max_observation_chars: int
) -> tuple[dict[str, Any], list[dict[str, Any]], set[str], set[str], dict[str, Any]]:
    toolbox = ToolBox(resources, kind, max_observation_chars)
    catalog = [{key: paper.get(key) for key in ("paper_id", "title", "doi")} for paper in resources["papers"]]
    messages = [
        {"role": "system", "content": agent_protocol(kind, max_rounds)},
        {
            "role": "user",
            "content": f"Question:\n{case['question']}\n\nThe frozen candidate-paper scope is:\n{json.dumps(catalog, ensure_ascii=False)}",
        },
    ]
    transcript = []
    tool_calls = 0
    for round_index in range(max_rounds):
        parsed, raw, runtime = client.call(messages)
        action = clean(parsed.get("action")).lower()
        transcript.append({"round": round_index + 1, "model": parsed, "raw_response": raw, "runtime": runtime})
        if action == "final" or (not action and clean(parsed.get("answer"))):
            return normalize_final(parsed), transcript, toolbox.exposed_ids, toolbox.exposed_paper_ids, {"tool_calls": tool_calls}
        arguments = parsed.get("arguments") if isinstance(parsed.get("arguments"), dict) else {}
        observation = toolbox.call(action, arguments)
        tool_calls += 1
        transcript[-1]["tool_action"] = action
        transcript[-1]["tool_arguments"] = arguments
        transcript[-1]["tool_observation"] = observation
        messages.extend(
            [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Tool observation:\n{json.dumps(observation, ensure_ascii=False)}"},
            ]
        )
    messages.append(
        {
            "role": "user",
            "content": f"The tool-call limit is reached. Return action=final now, using exactly this final schema: {FINAL_SCHEMA_TEXT}",
        }
    )
    parsed, raw, runtime = client.call(messages)
    transcript.append({"round": max_rounds + 1, "forced_final": True, "model": parsed, "raw_response": raw, "runtime": runtime})
    return normalize_final(parsed), transcript, toolbox.exposed_ids, toolbox.exposed_paper_ids, {"tool_calls": tool_calls}


def record_diagnostics(
    case: dict[str, Any], response: dict[str, Any], valid_ids: set[str], exposed_papers: set[str], transcript: list[dict[str, Any]], extra: dict[str, Any]
) -> dict[str, Any]:
    citations = canonical_citations(response)
    source_papers = {clean(item) for item in case.get("source_paper_ids_for_audit_only", [])}
    runtimes = [item.get("runtime", {}) for item in transcript]
    usage_rows = [runtime.get("usage", {}) for runtime in runtimes]
    prompt_tokens = sum(int(row.get("prompt_tokens") or 0) for row in usage_rows)
    completion_tokens = sum(int(row.get("completion_tokens") or 0) for row in usage_rows)
    return {
        "schema_valid": (
            all(key in response for key in ("answer", "conclusion", "claims", "evidence_citations", "quantitative_facts"))
            and bool(clean(response.get("answer")))
            and not response.get("parse_warning")
        ),
        "abstained": response.get("conclusion") == "INSUFFICIENT_EVIDENCE",
        "citation_count": len(citations),
        "citation_identifier_validity": sum(item in valid_ids for item in citations) / len(citations) if citations else None,
        "target_paper_retrieval": len(source_papers & exposed_papers) / len(source_papers) if source_papers else None,
        "exposed_paper_count": len(exposed_papers),
        "model_call_count": len(transcript),
        "tool_call_count": int(extra.get("tool_calls") or 0),
        "latency_seconds": round(sum(float(row.get("seconds") or 0) for row in runtimes), 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {}
    for method in METHODS:
        rows = [row for row in records if row.get("method_id") == method and not row.get("error")]

        def mean(key: str) -> float | None:
            values = [row.get("diagnostics", {}).get(key) for row in rows]
            values = [float(value) for value in values if value is not None]
            return statistics.fmean(values) if values else None

        summary[method] = {
            "completed": len(rows),
            "errors": sum(row.get("method_id") == method and bool(row.get("error")) for row in records),
            "schema_validity": mean("schema_valid"),
            "abstention_rate": mean("abstained"),
            "citation_identifier_validity": mean("citation_identifier_validity"),
            "target_paper_retrieval": mean("target_paper_retrieval"),
            "mean_model_calls": mean("model_call_count"),
            "mean_tool_calls": mean("tool_call_count"),
            "mean_latency_seconds": mean("latency_seconds"),
            "mean_prompt_tokens": mean("prompt_tokens"),
            "mean_completion_tokens": mean("completion_tokens"),
        }
    return summary


def write_blind_pack(cases: list[dict[str, Any]], records: list[dict[str, Any]], model: str, output_dir: Path) -> None:
    by_key = {(row["case_id"], row["method_id"]): row for row in records if not row.get("error")}
    review_rows = []
    keys = []
    for case in cases:
        if not all((case["case_id"], method) in by_key for method in METHODS):
            continue
        order = list(METHODS)
        random.Random(f"fig4-20260808:{model}:{case['case_id']}").shuffle(order)
        mapping = dict(zip("ABCDE", order))
        keys.append({"case_id": case["case_id"], "model": model, **mapping})
        row: dict[str, Any] = {
            "case_id": case["case_id"], "task_type": case.get("task_type"), "controller_group": model,
            "question": case["question"],
        }
        for letter, method in mapping.items():
            row[f"response_{letter}"] = json.dumps(by_key[(case["case_id"], method)]["response"], ensure_ascii=False, indent=2)
            for metric in (
                "scientific_correctness_0_to_4", "claim_evidence_entailment_0_to_4",
                "evidence_completeness_0_to_4", "demonstrated_vs_proposed_boundary_0_to_4",
                "appropriate_abstention_0_or_1",
            ):
                row[f"{metric}_{letter}"] = ""
        row["expert_notes"] = ""
        review_rows.append(row)
    if not review_rows:
        return
    with (output_dir / "blind_expert_review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(review_rows[0]))
        writer.writeheader()
        writer.writerows(review_rows)
    write_json(output_dir / "blind_key_DO_NOT_SHARE.json", keys)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--compatibility", choices=("deepseek", "openai"), default="openai")
    parser.add_argument("--methods", default=",".join(METHODS))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-context-chars", type=int, default=18000)
    parser.add_argument("--max-observation-chars", type=int, default=18000)
    parser.add_argument("--max-agent-rounds", type=int, default=4)
    parser.add_argument("--max-output-tokens", type=int, default=1600)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--chunk-words", type=int, default=220)
    parser.add_argument("--overlap-words", type=int, default=40)
    parser.add_argument("--pdf-root", type=Path, action="append", default=[])
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    methods = tuple(item.strip() for item in args.methods.split(",") if item.strip())
    unknown = set(methods) - set(METHODS)
    if unknown:
        raise ValueError(f"Unknown methods: {sorted(unknown)}")
    if not args.db.is_file():
        raise FileNotFoundError(args.db)
    benchmark = load_json(args.benchmark)
    stop = args.offset + args.limit if args.limit else None
    cases = benchmark["cases"][args.offset : stop]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    resource_dir = args.output_dir / "resources"
    record_dir = args.output_dir / "records"
    resource_dir.mkdir(exist_ok=True)
    record_dir.mkdir(exist_ok=True)
    pdf_roots = args.pdf_root or list(DEFAULT_PDF_ROOTS)
    preparation_signature = {
        "database_file": args.db.name, "db_mtime_ns": args.db.stat().st_mtime_ns,
        "plain_text_source": "matched_destructured_article_excerpts_v1",
        "chunk_words": args.chunk_words, "overlap_words": args.overlap_words,
        "pdf_root_count": len(pdf_roots),
    }
    resources_by_case = {}
    for index, case in enumerate(cases, 1):
        cache = resource_dir / f"{case['case_id']}.json"
        saved = load_json(cache) if cache.exists() else None
        if not saved or saved.get("preparation_signature") != preparation_signature:
            resources = prepare_resources(
                case, args.db, args.output_dir / "cache", pdf_roots, args.chunk_words, args.overlap_words
            )
            saved = {"preparation_signature": preparation_signature, "resources": resources}
            write_json(cache, saved)
        resources_by_case[case["case_id"]] = saved["resources"]
        counts = saved["resources"]["resource_counts"]
        print(
            f"[prepare {index}/{len(cases)}] {case['case_id']} text={counts['text_excerpts']} "
            f"mechanisms={counts['mechanisms']} evidence={counts['evidence']} "
            f"pdf_failures={len(saved['resources']['extraction_failures'])}", flush=True,
        )
    write_json(
        args.output_dir / "preparation_summary.json",
        {
            "signature": preparation_signature,
            "cases": [
                {
                    "case_id": case["case_id"],
                    "resource_counts": resources_by_case[case["case_id"]]["resource_counts"],
                    "extraction_failures": resources_by_case[case["case_id"]]["extraction_failures"],
                }
                for case in cases
            ],
        },
    )
    write_json(
        args.output_dir / "expert_audit_sourcebook_DO_NOT_USE_FOR_GENERATION.json",
        {
            "warning": "Post-generation expert audit only. The runner never inserts these audit labels into model prompts.",
            "cases": [
                {
                    "case_id": case["case_id"],
                    "question": case["question"],
                    "source_paper_ids": case.get("source_paper_ids_for_audit_only", []),
                    "reference": case.get("reference_for_expert_audit_only", {}),
                    "source_mechanisms": [
                        compact_mechanism(row)
                        for row in resources_by_case[case["case_id"]]["mechanisms"]
                        if row["paper_id"] in set(case.get("source_paper_ids_for_audit_only", []))
                    ],
                    "source_evidence": [
                        compact_evidence(row)
                        for row in resources_by_case[case["case_id"]]["evidence"]
                        if row["paper_id"] in set(case.get("source_paper_ids_for_audit_only", []))
                    ],
                }
                for case in cases
            ],
        },
    )
    if args.prepare_only:
        print("Preparation complete; no model calls made.")
        return 0

    api_key = clean(os.environ.get(args.api_key_env))
    if not api_key and args.compatibility == "openai" and args.api_base.startswith("http://"):
        api_key = "local-not-secret"
    if not api_key:
        raise RuntimeError(f"Required API key environment variable is not set: {args.api_key_env}")
    client = ChatClient(
        args.api_base, api_key, args.model, args.compatibility, args.max_output_tokens, args.timeout, args.retries
    )
    run_config = {
        "experiment_id": "ms3_fig4_2llm_x_5access_20260808",
        "model": args.model,
        "api_base": args.api_base,
        "compatibility": args.compatibility,
        "methods": methods,
        "max_context_chars": args.max_context_chars,
        "max_observation_chars": args.max_observation_chars,
        "max_agent_rounds": args.max_agent_rounds,
        "max_output_tokens": args.max_output_tokens,
        "temperature": 0,
        "benchmark_sha256": sha256_json(benchmark),
        "preparation_signature": preparation_signature,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    run_signature = sha256_json(run_config)
    records_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    def run_one(case: dict[str, Any], method: str) -> dict[str, Any]:
        cache = record_dir / f"{case['case_id']}__{method}.json"
        if cache.exists() and not args.force:
            saved = load_json(cache)
            if saved.get("run_signature") == run_signature and not saved.get("error"):
                return saved
        resources = resources_by_case[case["case_id"]]
        try:
            if method in {"direct", "text_rag", "ms3_rag"}:
                response, transcript, valid_ids, papers, extra = run_static(
                    case, method, resources, client, args.max_context_chars
                )
            else:
                response, transcript, valid_ids, papers, extra = run_agent(
                    case, "text" if method == "text_agent" else "ms3", resources, client,
                    args.max_agent_rounds, args.max_observation_chars,
                )
            record = {
                "case_id": case["case_id"], "task_type": case.get("task_type"), "method_id": method,
                "model": args.model, "question": case["question"], "response": response,
                "diagnostics": record_diagnostics(case, response, valid_ids, papers, transcript, extra),
                "transcript": transcript, "valid_observed_citation_ids": sorted(valid_ids),
                "access_trace": extra,
                "run_signature": run_signature,
            }
        except Exception as exc:  # noqa: BLE001
            record = {
                "case_id": case["case_id"], "task_type": case.get("task_type"), "method_id": method,
                "model": args.model, "question": case["question"], "error": repr(exc),
                "run_signature": run_signature,
            }
        write_json(cache, record)
        return record

    jobs = [(case, method) for case in cases for method in methods]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {executor.submit(run_one, case, method): (case, method) for case, method in jobs}
        for index, future in enumerate(concurrent.futures.as_completed(future_map), 1):
            case, method = future_map[future]
            record = future.result()
            records_by_key[(case["case_id"], method)] = record
            ordered = [
                records_by_key[key]
                for key in sorted(records_by_key, key=lambda item: ([row["case_id"] for row in cases].index(item[0]), METHODS.index(item[1])))
            ]
            with WRITE_LOCK:
                write_json(
                    args.output_dir / "results.partial.json",
                    {"status": "running", "run_config": run_config, "completed": len(ordered), "expected": len(jobs), "records": ordered},
                )
            print(
                f"[model {index}/{len(jobs)}] {case['case_id']} {method} "
                f"status={'ERROR' if record.get('error') else record['response']['conclusion']}", flush=True,
            )

    records = [records_by_key[(case["case_id"], method)] for case in cases for method in methods]
    payload = {
        "status": "generation_complete; blind expert review required before reporting",
        "run_config": run_config,
        "case_count": len(cases),
        "record_count": len(records),
        "automatic_summary": aggregate(records),
        "scientific_metrics_status": "Not computed until blind materials-domain expert review",
        "records": records,
    }
    write_json(args.output_dir / "results.json", payload)
    write_json(args.output_dir / "summary.json", payload["automatic_summary"])
    write_blind_pack(cases, records, args.model, args.output_dir)
    print(f"Completed {len(records)} records in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
