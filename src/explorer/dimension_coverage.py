"""Committed evidence for every admitted dimension value (issue #110).

``dimension_coverage.csv`` has one row per value of each admitted dimension in
``model.json``, in model order. Every column is generated:

- ``smoke_run`` / ``smoke_test`` / ``smoke_result``: the value's smoke run (``model.json``,
  from ``surface_candidates.csv``'s ``smoke_runs``), the test it ran and its result, read
  from the run's ``manifest.json`` in ``runs/smoke/``;
- ``campaign_runs`` / ``contrast_runs``: the committed accepted adapter runs
  (``contrasts.accepted_runs``: ``ACCEPTED``, passing today's rules, pinned commits, known
  harness) in ``campaigns/`` and ``contrasts/runs/`` whose candidate has this value
  (``pruning.current_label``), as ``N runs: id; id; ...``;
- ``current_harness_runs``: how many of those ran under today's harness
  (``cache.harness_digest``);
- ``status``: ``COVERED`` (the smoke run passed and at least one accepted run has the
  value), ``SMOKE_ONLY`` (only the smoke run), ``RUNS_ONLY`` (accepted runs but no passing
  smoke run) or ``GAP`` (neither).

Runs under different harnesses are counted together: the question is whether the value
executes, not what a run logged. Nothing here interprets behavior.

``scripts/update_dimension_coverage.py`` rewrites the file; ``tests/test_dimension_coverage.py``
fails when it's stale.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DIMENSION_CSV = REPO_ROOT / "dimension_coverage.csv"
SMOKE_DIR = REPO_ROOT / "runs" / "smoke"
COLUMNS = ("dimension", "category", "kind", "value", "smoke_run", "smoke_test",
           "smoke_result", "campaign_runs", "contrast_runs", "current_harness_runs",
           "status")
STATUSES = ("COVERED", "SMOKE_ONLY", "RUNS_ONLY", "GAP")


def smoke(run_id: str | None) -> tuple[str, str]:
    """(test, result) of a smoke run from its manifest; ("", "MISSING") if not committed."""
    manifest = SMOKE_DIR / str(run_id) / "manifest.json"
    if not run_id or not manifest.exists():
        return "", "MISSING"
    data = json.loads(manifest.read_text())
    tests = [r["test"] for r in data.get("results", []) if r.get("result") != "NOTRUN"]
    return "; ".join(tests), data.get("overall", "")


def _runs(found: list) -> str:
    found = sorted(found, key=lambda run: run.run_id)
    return f"{len(found)} runs: " + "; ".join(r.run_id for r in found) if found else "0 runs"


def coverage_rows(model: dict | None = None, runs: list | None = None) -> list[dict[str, str]]:
    """One row per admitted dimension value, in model.json order."""
    from explorer.cache import harness_digest
    from explorer.contrasts import accepted_runs
    from explorer.model_json import MODEL_JSON
    from explorer.pruning import current_label
    model = json.loads(MODEL_JSON.read_text()) if model is None else model
    runs = accepted_runs() if runs is None else runs
    current = harness_digest()
    out = []
    for dim in model["dimensions"]:
        labels = [(current_label(candidate, dim["name"]), run) for candidate, run in runs]
        for value in dim["values"]:
            matching = [run for label, run in labels if label == value["label"]]
            campaign = [r for r in matching if r.folder.startswith("campaigns/")]
            contrast = [r for r in matching if r.folder.startswith("contrasts/")]
            test, result = smoke(value.get("smoke_run"))
            if result == "PASS":
                status = "COVERED" if matching else "SMOKE_ONLY"
            else:
                status = "RUNS_ONLY" if matching else "GAP"
            out.append({
                "dimension": dim["name"], "category": dim["category"], "kind": dim["kind"],
                "value": value["label"], "smoke_run": value.get("smoke_run") or "",
                "smoke_test": test, "smoke_result": result,
                "campaign_runs": _runs(campaign), "contrast_runs": _runs(contrast),
                "current_harness_runs": str(sum(r.harness == current for r in matching)),
                "status": status,
            })
    return out


def render() -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(coverage_rows())
    return buf.getvalue()


def rows(path: Path = DIMENSION_CSV) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(path: Path = DIMENSION_CSV) -> None:
    Path(path).write_text(render(), encoding="utf-8")
