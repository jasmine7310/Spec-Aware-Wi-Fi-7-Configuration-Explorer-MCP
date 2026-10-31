import csv
import os
import re
from pathlib import Path

import pytest

CSV_PATH = Path(__file__).resolve().parent.parent / "surface_candidates.csv"
COLUMNS = ["name", "category", "kind", "side", "values", "source",
           "hostap_option_or_helper", "example_tests", "notes"]
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
