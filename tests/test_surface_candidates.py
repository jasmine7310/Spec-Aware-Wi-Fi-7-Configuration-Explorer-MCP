import csv
import json
import os
import re
from pathlib import Path

import pytest

from explorer.scenarios import TEST_CONFIGS
from explorer.validate import run_p1_checks

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "surface_candidates.csv"
COLUMNS = ["name", "category", "kind", "side", "values", "source",
           "hostap_option_or_helper", "example_tests", "notes", "smoke_runs"]
# Committed run evidence a smoke_runs entry may point to.
EVIDENCE_DIRS = [REPO_ROOT / "runs" / d for d in ("baseline", "calibration", "smoke")]
# e.g. "SAE=1793690818; OWE=1793690841"
SMOKE_ENTRY = re.compile(r"^(?P<value>[^=;]+)=(?P<run_id>\d+)$")
CATEGORIES = {"security", "key", "link", "management"}
KINDS = {"config", "action", "observation"}
SIDES = {"ap", "sta", "both"}
# e.g. "tests/hwsim/test_eht.py:320"
SOURCE_REF = re.compile(r"^tests/hwsim/[\w.]+\.py:\d+$")


def _rows():
    with CSV_PATH.open(newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == COLUMNS
        return list(reader)


def _refs(row):
    return [ref.strip() for ref in row["source"].split(";")]


def test_has_at_least_12_candidates():
    assert len(_rows()) >= 12


def test_names_are_unique():
    names = [row["name"] for row in _rows()]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["name"])
def test_row_is_well_formed(row):
    assert row["category"] in CATEGORIES
    assert row["kind"] in KINDS
    assert row["side"] in SIDES
    assert row["source"], "every candidate needs a source file and line"
    for ref in _refs(row):
        assert SOURCE_REF.match(ref), ref
    if row["kind"] == "config":
        assert row["values"], "config candidates list the values seen in the code"


def _smoke_runs(row):
    if not row["smoke_runs"]:
        return {}
    entries = [SMOKE_ENTRY.match(e.strip()) for e in row["smoke_runs"].split(";")]
    assert all(entries), f"{row['name']}: smoke_runs must be 'value=run_id; ...'"
    return {m["value"]: m["run_id"] for m in entries}


def test_at_least_4_candidates_smoke_tested_with_2_values():
    # Issue "Smoke test 4 settings": >=4 settings or actions, each with >=2 values run.
    tested = [row["name"] for row in _rows() if len(_smoke_runs(row)) >= 2]
    assert len(tested) >= 4, tested


@pytest.mark.parametrize("row", [r for r in _rows() if r["smoke_runs"]],
                         ids=lambda row: row["name"])
def test_smoke_runs_are_committed_passing_runs(row):
    for value, run_id in _smoke_runs(row).items():
        folders = [d / run_id for d in EVIDENCE_DIRS if (d / run_id).is_dir()]
        assert len(folders) == 1, f"{row['name']}={value}: no committed run {run_id}"
        manifest = json.loads((folders[0] / "manifest.json").read_text())
        assert manifest["overall"] == "PASS", f"{row['name']}={value}: run {run_id}"


@pytest.mark.parametrize("row", [r for r in _rows() if r["smoke_runs"]],
                         ids=lambda row: row["name"])
def test_smoke_tested_values_pass_modeled_rules(row):
    # A value only counts if the run that shows it executes is also legal under the
    # coded P1 rules (e.g. plain SAE between EHT devices breaks 802.11be §12.12.9).
    for value, run_id in _smoke_runs(row).items():
        folder = next(d / run_id for d in EVIDENCE_DIRS if (d / run_id).is_dir())
        for result in json.loads((folder / "manifest.json").read_text())["results"]:
            config = TEST_CONFIGS.get(result["test"])
            assert config is not None, f"{row['name']}={value}: {result['test']} has no scenario"
            assert run_p1_checks(config) == [], f"{row['name']}={value}: {result['test']}"


def test_covers_security_key_and_link():
    # The spec's dimensions must span security, key lifecycle and link lifecycle.
    categories = {row["category"] for row in _rows()}
    assert {"security", "key", "link"} <= categories


@pytest.mark.skipif(not os.environ.get("WIFI7_HOSTAP_SRC"),
                    reason="set WIFI7_HOSTAP_SRC to a hostap checkout at the pinned commit")
def test_sources_exist_in_pinned_hostap():
    root = Path(os.environ["WIFI7_HOSTAP_SRC"])
    cache = {}
    for row in _rows():
        for ref in _refs(row):
            path, line = ref.rsplit(":", 1)
            lines = cache.setdefault(path, (root / path).read_text().splitlines())
            assert 1 <= int(line) <= len(lines), ref
            assert lines[int(line) - 1].strip(), f"{ref} is a blank line"
