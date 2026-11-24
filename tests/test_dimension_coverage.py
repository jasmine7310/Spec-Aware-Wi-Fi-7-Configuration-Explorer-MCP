"""dimension_coverage.csv (#110): committed evidence for every admitted dimension value."""

import json

import pytest

from explorer import dimension_coverage as dc
from explorer.model_json import MODEL_JSON


def _model():
    return json.loads(MODEL_JSON.read_text())


def test_csv_is_current():
    assert dc.DIMENSION_CSV.read_text(encoding="utf-8") == dc.render(), (
        "dimension_coverage.csv is stale: run scripts/update_dimension_coverage.py")


def test_one_row_per_admitted_value_in_model_order():
    rows = dc.rows()
    assert list(rows[0]) == list(dc.COLUMNS)
    assert [(r["dimension"], r["value"]) for r in rows] == [
        (d["name"], v["label"]) for d in _model()["dimensions"] for v in d["values"]]
    assert all(r["status"] in dc.STATUSES for r in rows)


def test_every_admitted_value_is_covered():
    # The issue's "done when": no admitted value without committed evidence. A new value
    # needs a passing smoke run and at least one accepted run, or a documented gap.
    gaps = [(r["dimension"], r["value"], r["status"]) for r in dc.rows()
            if r["status"] != "COVERED"]
    assert not gaps, gaps


@pytest.mark.parametrize("row", dc.rows(), ids=lambda r: f"{r['dimension']}={r['value']}")
def test_counts_match_the_listed_runs(row):
    total = 0
    for column in ("campaign_runs", "contrast_runs"):
        count, _, ids = row[column].partition(" runs")
        listed = [i.strip() for i in ids.removeprefix(":").split(";") if i.strip()]
        assert int(count) == len(listed) == len(set(listed)), column
        total += len(listed)
    assert 0 <= int(row["current_harness_runs"]) <= total


def test_status_follows_the_evidence():
    from explorer.contrasts import accepted_runs
    from explorer.pruning import current_label
    runs = accepted_runs()
    by_label = {current_label(c, "link_remove"): (c, r) for c, r in runs}
    model = {"dimensions": [{"name": "link_remove", "category": "link", "kind": "action",
                             "values": [{"label": "present", "smoke_run": "1793897945"},
                                        {"label": "absent", "smoke_run": None}]}]}
    status = lambda found: [r["status"] for r in dc.coverage_rows(model, found)]
    # present: a passing smoke run (eht_mld_link_removal_client_bp); absent: none committed.
    assert status([]) == ["SMOKE_ONLY", "GAP"]
    assert status([by_label["present"]]) == ["COVERED", "GAP"]
    assert status([by_label["absent"]]) == ["SMOKE_ONLY", "RUNS_ONLY"]
    assert dc.smoke("1793897945") == ("eht_mld_link_removal_client_bp", "PASS")
    assert dc.smoke("0") == ("", "MISSING")
