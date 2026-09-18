#!/usr/bin/env python3
"""Build a small copyright-safe SQLite database for the MS³ tool demo."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


SCHEMA = """
create table papers (
    paper_id text primary key, title text, doi text, year integer,
    paper_type text, corpus_domain text, primary_task text
);
create table mechanisms (
    mechanism_uid text primary key, paper_id text, mechanism_id text,
    mechanism_statement text, material text, sensor text, signal text,
    system text, evidence_chain_json text
);
create table evidence (
    evidence_uid text primary key, paper_id text, evidence_id text,
    evidence_type text, evidence_subtype text, section text,
    figure_or_table text, article_excerpt_text text,
    supports_elements_json text, supports_relations_json text, raw_json text
);
create virtual table mechanism_fts using fts5(
    mechanism_uid unindexed, paper_id unindexed, searchable_text
);
create virtual table evidence_fts using fts5(
    evidence_uid unindexed, paper_id unindexed, searchable_text
);
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        if not args.force:
            raise SystemExit(f"Refusing to overwrite {args.output}; pass --force")
        args.output.unlink()

    record = json.loads(args.record.read_text(encoding="utf-8"))
    paper = record["paper"]
    mechanism = record["mechanisms"][0]
    path = mechanism["path"]
    args.output.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(args.output)
    try:
        connection.executescript(SCHEMA)
        connection.execute(
            "insert into papers values (?,?,?,?,?,?,?)",
            (
                paper["paper_id"], paper["title"], paper.get("doi"),
                paper.get("year"), "illustrative record", "demonstration",
                "tool smoke test",
            ),
        )
        mechanism_uid = f"{paper['paper_id']}:{mechanism['mechanism_id']}"
        statement = " -> ".join(
            path[role] for role in ("material", "sensor", "signal", "system")
        )
        connection.execute(
            "insert into mechanisms values (?,?,?,?,?,?,?,?,?)",
            (
                mechanism_uid, paper["paper_id"], mechanism["mechanism_id"],
                statement, path["material"], path["sensor"], path["signal"],
                path["system"], json.dumps(mechanism["evidence_chain"]),
            ),
        )
        connection.execute(
            "insert into mechanism_fts values (?,?,?)",
            (mechanism_uid, paper["paper_id"], statement),
        )

        for evidence in record["evidence"]:
            evidence_uid = f"{paper['paper_id']}:{evidence['evidence_id']}"
            relation = evidence["supports"][0]
            excerpt = (
                "Synthetic demonstration text: the illustrative record supports "
                f"the {relation} relation in a strain-sensing pathway."
            )
            raw = {"source_location": evidence["source"], "demo_only": True}
            connection.execute(
                "insert into evidence values (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    evidence_uid, paper["paper_id"], evidence["evidence_id"],
                    evidence["role"], "illustrative",
                    evidence["source"].get("section"),
                    evidence["source"].get("figure_or_table"), excerpt,
                    json.dumps([relation.split("->")[0]]),
                    json.dumps([relation]), json.dumps(raw),
                ),
            )
            connection.execute(
                "insert into evidence_fts values (?,?,?)",
                (evidence_uid, paper["paper_id"], f"{excerpt} {statement}"),
            )
        connection.commit()
    finally:
        connection.close()
    print(f"demo database: {args.output}")
    print("records: 1 paper, 1 mechanism, 3 evidence items")


if __name__ == "__main__":
    main()
