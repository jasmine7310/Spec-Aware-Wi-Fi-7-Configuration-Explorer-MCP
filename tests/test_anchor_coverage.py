import csv
import json
import os
import re
from pathlib import Path

import pytest

from explorer.scenarios import CLIENT_BP_SUFFIX, TEST_CONFIGS
from explorer.signatures import extract_record
from explorer.validate import run_p1_checks

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "anchor_coverage.csv"
CANDIDATES = REPO_ROOT / "surface_candidates.csv"
COLUMNS = ["family_id", "name", "category", "source_test", "source_helpers",
           "modeled_dimensions", "run_ids", "observed_signature", "status",
           "campaign_runs", "campaign_observed"]   # the last two generated (#77)
STATUSES = {"PLANNED", "IN_PROGRESS", "PASS", "FAIL", "BLOCKED"}
EVIDENCE_DIRS = [REPO_ROOT / "runs" / d for d in ("baseline", "calibration", "smoke", "anchors")]
# The roadmap: at least 3 independent clean runs per anchor family.
RUNS_FOR_PASS = 3


def _rows():
    with CSV_PATH.open(newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == COLUMNS
        return list(reader)


def _split(value):
    return [part.strip() for part in value.split(";") if part.strip()]


def _run_folder(run_id):
    folders = [d / run_id for d in EVIDENCE_DIRS if (d / run_id).is_dir()]
    assert len(folders) == 1, f"no committed run {run_id}"
    return folders[0]


def _manifest(run_id):
    return json.loads((_run_folder(run_id) / "manifest.json").read_text())


def test_four_families_cover_security_key_and_link():
    rows = _rows()
    assert len(rows) >= 4
    assert len({row["family_id"] for row in rows}) == len(rows)
    assert {"security", "key", "link"} <= {row["category"] for row in rows}


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["family_id"])
def test_row_is_well_formed(row):
    assert re.fullmatch(r"F\d{2}", row["family_id"])
    assert row["status"] in STATUSES
    with CANDIDATES.open(newline="") as f:
        candidates = {r["name"] for r in csv.DictReader(f)}
    dimensions = _split(row["modeled_dimensions"])
    assert dimensions and set(dimensions) <= candidates, dimensions
    if row["status"] == "PASS":
        assert len(_split(row["run_ids"])) >= RUNS_FOR_PASS


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["family_id"])
def test_run_ids_are_committed_passing_runs_of_the_source_test(row):
    for run_id in _split(row["run_ids"]):
        results = {r["test"]: r["result"] for r in _manifest(run_id)["results"]}
        assert results.get(row["source_test"]) == "PASS", f"{row['family_id']}: {run_id}"


@pytest.mark.parametrize("row", [r for r in _rows() if r["status"] == "PASS"],
                         ids=lambda row: row["family_id"])
def test_pass_means_the_runs_reproduce_the_same_behavior(row):
    # A PASS family's runs are independent fresh guests whose behavior signatures match.
    signatures = [extract_record(_run_folder(run_id), row["source_test"]).signature()
                  for run_id in _split(row["run_ids"])]
    assert all(s == signatures[0] for s in signatures), row["family_id"]


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["family_id"])
def test_source_test_passes_modeled_rules(row):
    # Anchors are legal experiments: a configuration that breaks a modeled rule
    # (e.g. plain SAE, 802.11be §12.12.9) can only be a negative experiment.
    assert row["source_test"] in TEST_CONFIGS
    assert run_p1_checks(TEST_CONFIGS[row["source_test"]]) == []


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["family_id"])
def test_runs_show_client_beacon_protection_on(row):
    # 802.11be §12.12.9: the setting was issued, and the client installed the key.
    for run_id in _split(row["run_ids"]):
        log = (_run_folder(run_id) / f"{row['source_test']}.log5").read_text(errors="replace")
        assert "SET_NETWORK 0 beacon_prot 1" in log, run_id
        assert re.search(r"MLO Link \d+ BIGTK keyid", log), run_id


def _test_function(source, test):
    # The body of "def test_<name>(" up to the next top-level def.
    match = re.search(rf"^def test_{test}\(.*?(?=^def )", source, re.MULTILINE | re.DOTALL)
    assert match, f"test_{test} not found"
    return match.group(0)


@pytest.mark.skipif(not os.environ.get("WIFI7_HOSTAP_SRC"),
                    reason="set WIFI7_HOSTAP_SRC to a hostap checkout at the pinned commit")
@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["family_id"])
def test_helpers_are_called_by_the_pinned_test(row):
    source = (Path(os.environ["WIFI7_HOSTAP_SRC"]) / "tests/hwsim/test_eht.py").read_text()
    # A _client_bp wrapper runs hostap's own test with client beacon protection on.
    body = _test_function(source, row["source_test"].removesuffix(CLIENT_BP_SUFFIX))
    for helper in (h.strip() for h in row["source_helpers"].split(",")):
        assert f"{helper.split('.')[-1]}(" in body, f"{row['family_id']}: {helper}"


# --- campaign evidence per family (#77) ---------------------------------------------------


def test_campaign_columns_are_current():
    from explorer import anchors
    assert CSV_PATH.read_text() == anchors.render(), (
        "anchor_coverage.csv's campaign columns are out of date: "
        "run scripts/update_anchor_coverage.py")


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["family_id"])
def test_campaign_runs_have_the_family_s_values(row):
    from explorer import anchors, contrasts
    from explorer.pruning import current_label
    accepted = {run.run_id: candidate for candidate, run in contrasts.accepted_runs()}
    count, _, listed = row["campaign_runs"].partition(" runs: ")
    run_ids = _split(listed)
    assert int(count) == len(run_ids) > 0
    wanted = anchors.family_labels(row)
    for run_id in run_ids:
        # Each is a committed accepted, rule-passing adapter run with the family's own
        # value for every modeled dimension.
        assert run_id in accepted, run_id
        assert {d: current_label(accepted[run_id], d) for d in wanted} == wanted, run_id
    # Every behavior fact of the family is counted over all of those runs.
    facts = row["campaign_observed"].split("; ")
    assert [f.split(": ")[0] for f in facts] == list(anchors.FAMILY_FACTS[row["family_id"]])
    for fact in facts:
        counts = re.findall(r" x(\d+)(?:,|$)", fact)
        assert sum(map(int, counts)) == len(run_ids), fact


def test_family_values_come_from_the_source_test():
    from explorer import anchors
    labels = {row["family_id"]: anchors.family_labels(row) for row in _rows()}
    assert labels == {
        "F02": {"ap_akm": "SAE-EXT-KEY", "sta_akm": "SAE-EXT-KEY"},
        "F08": {"ap_ptk_rekey_interval": "5"},
        "F09": {"ap_gtk_rekey_interval": "5"},
        "F06": {"link_remove": "present", "rekey_gtk_now": "present"},
    }


def test_a_station_status_key_is_read_inside_the_fact():
    from explorer import anchors
    from explorer.signatures import UNKNOWN
    facts = {"station_status": {"key_mgmt": "OWE"}, "ptk_rekeys_completed": 1}
    assert anchors.fact_value(facts, "station_status.key_mgmt") == "OWE"
    assert anchors.fact_value(facts, "station_status.pmf") == UNKNOWN
    assert anchors.fact_value({"station_status": UNKNOWN}, "station_status.key_mgmt") == UNKNOWN
    assert anchors.fact_value(facts, "gtk_rekeys_completed") == UNKNOWN
