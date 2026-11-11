"""Checks spec_coverage.csv, the spec coverage matrix (issue #62): which clauses of the
standards in docs/references.md the model covers, and how."""

import csv
import re
from pathlib import Path

import pytest

from explorer.rules import load_rules

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "spec_coverage.csv"
COLUMNS = ["document", "clause", "page", "requirement_summary", "strength", "status",
           "rule_ids", "fixtures", "run_evidence", "notes"]
STANDARDS = {"IEEE-802.11be-2024", "IEEE-802.11-2024", "WFA-WPA3"}
# The rules.yaml strength vocabulary, minus "code": the matrix covers the standards.
STRENGTHS = {"shall", "note", "unclassified", "guidance"}
STATUSES = {"RULE", "UND", "OUT_OF_SCOPE", "TODO"}
RUN_DIRS = [REPO_ROOT / "runs" / d for d in ("baseline", "calibration", "smoke", "anchors")]
# Clause and table numbers in a location, e.g. "§12.4.4.2.3 (ECC)" or "Table 9-373, bit 5"
CLAUSE_TOKEN = re.compile(r"§\s?\d+(?:\.\d+)*|Table \d+(?:-\d+)?")
# Long verbatim text from the licensed PDFs must not be committed; summaries are ours.
MAX_SUMMARY_CHARS = 300


def _rows():
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == COLUMNS
        return list(reader)


def _split(value):
    return [part.strip() for part in value.split(";") if part.strip()]


def _tokens(text):
    return {t.replace("§ ", "§") for t in CLAUSE_TOKEN.findall(text)}


def _row_id(row):
    return f"{row['document']} {row['clause']}"


@pytest.mark.parametrize("row", _rows(), ids=_row_id)
def test_row_is_well_formed(row):
    assert row["document"] in STANDARDS
    assert row["clause"] and row["requirement_summary"] and row["page"]
    assert len(row["requirement_summary"]) <= MAX_SUMMARY_CHARS
    assert row["strength"] in STRENGTHS
    assert row["status"] in STATUSES
    if row["page"] == "TBD" or row["clause"].startswith("TBD"):
        # An unread clause can't be a rule yet.
        assert row["status"] in {"TODO", "OUT_OF_SCOPE"}, "find the clause and page first"


@pytest.mark.parametrize("row", _rows(), ids=_row_id)
def test_status_matches_rule_ids(row):
    registry = load_rules()
    known = {r.id for r in [*registry.rules, *registry.undetermined]}
    ids = _split(row["rule_ids"])
    assert all(i in known for i in ids), f"unknown rule IDs: {set(ids) - known}"
    if row["status"] == "RULE":
        assert ids, "a RULE row names the rule(s) built on it"
    elif row["status"] == "UND":
        assert ids and all(i.startswith("UND.") for i in ids)
    else:
        assert not ids, f"a {row['status']} row names no rule"
    if row["status"] in {"OUT_OF_SCOPE", "TODO"}:
        assert row["notes"], "say why it's out of scope, or what's left to do"


@pytest.mark.parametrize("row", [r for r in _rows() if r["fixtures"]], ids=_row_id)
def test_fixtures_exist(row):
    for fixture in _split(row["fixtures"]):
        path, _, name = fixture.partition("::")
        assert (REPO_ROOT / path).is_file(), fixture
        if name:
            assert re.search(rf"^def {re.escape(name)}\(", (REPO_ROOT / path).read_text(),
                             re.MULTILINE), fixture


@pytest.mark.parametrize("row", [r for r in _rows() if r["run_evidence"]], ids=_row_id)
def test_run_evidence_is_committed(row):
    for run_id in _split(row["run_evidence"]):
        assert any((d / run_id / "manifest.json").is_file() for d in RUN_DIRS), run_id


def test_every_cited_clause_is_in_the_matrix():
    # Every standards citation in rules.yaml has a matrix row for its clause or table,
    # and that row names the rule that cites it.
    rows = _rows()
    registry = load_rules()
    missing = []
    for rule in [*registry.rules, *registry.undetermined]:
        for citation in rule.sources:
            if citation.doc not in STANDARDS:
                continue
            for token in _tokens(citation.location):
                matches = [r for r in rows if r["document"] == citation.doc
                           and token in _tokens(r["clause"])]
                if not matches:
                    missing.append(f"{citation.doc} {token} (cited by {rule.id})")
                elif not any(rule.id in _split(r["rule_ids"]) for r in matches):
                    missing.append(f"{citation.doc} {token}: no row names {rule.id}")
    assert not missing, missing


def test_every_clause_in_references_is_in_the_matrix():
    # docs/references.md's "Relevant sections" table lists the clauses the research found.
    text = (REPO_ROOT / "docs" / "references.md").read_text()
    section = text.split("## Relevant sections", 1)[1].split("\n## ", 1)[0]
    rows = _rows()
    missing = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0].strip("`") not in STANDARDS:
            continue
        doc = cells[0].strip("`")
        for token in _tokens(cells[1]):
            # A parent clause (e.g. §35.3.7.5) is covered by rows for its subclauses.
            if not any(r["document"] == doc and any(t == token or t.startswith(token + ".")
                                                    for t in _tokens(r["clause"]))
                       for r in rows):
                missing.append(f"{doc} {token}")
    assert not missing, missing


def test_status_counts():
    counts = {s: sum(r["status"] == s for r in _rows()) for s in STATUSES}
    assert counts["RULE"] >= 4
    assert sum(counts.values()) == len(_rows())
