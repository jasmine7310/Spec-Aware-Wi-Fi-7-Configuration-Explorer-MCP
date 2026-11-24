"""final_verification.csv (#116): the runs verifying each anchor family and contrast side."""

import json

import pytest

from explorer import verification as v
from explorer.anchors import rows as anchor_rows


def test_csv_is_current():
    assert v.VERIFICATION_CSV.read_text(encoding="utf-8") == v.render(), (
        "final_verification.csv is stale: run scripts/update_verification.py")


def test_one_row_per_anchor_family_and_contrast_side():
    rows = v.rows()
    assert list(rows[0]) == list(v.COLUMNS)
    _, families = anchor_rows()
    expected = [f["family_id"] for f in families]
    expected += [f"{cid}:{side}" for cid, _ in v.reductions() for side, _, _ in v.SIDES]
    assert [r["id"] for r in rows] == expected
    assert {cid for cid, _ in v.reductions()} == {"c1", "c2", "c3"}  # not c3/first-attempt
    assert all(r["status"] in v.STATUSES for r in rows)


def test_nothing_failed():
    assert not [r["id"] for r in v.rows() if r["status"] == "FAILED"]


@pytest.mark.parametrize("row", v.rows(), ids=lambda r: r["id"])
def test_counts_match_the_listed_runs(row):
    count, _, ids = row["runs"].partition(" runs")
    listed = [i.strip() for i in ids.removeprefix(":").split(";") if i.strip()]
    assert int(count) == len(listed) == len(set(listed))
    assert 0 <= int(row["frozen_runs"]) <= int(row["passing_runs"]) <= len(listed)
    harness_total = sum(int(part.rsplit(" x", 1)[1]) for part in row["harnesses"].split("; ")
                        if part)
    assert harness_total == int(row["passing_runs"])


def test_contrast_sides_list_the_verification_runs():
    rows = {r["id"]: r for r in v.rows()}
    for cid, reduction in v.reductions():
        for side, key, _ in v.SIDES:
            ids = [e["run_id"] for e in reduction["verification"][key]]
            assert rows[f"{cid}:{side}"]["runs"] == f"{len(ids)} runs: " + "; ".join(ids)


def test_anchor_runs_come_from_the_evidence_folders_only():
    # 1793948173 is a git-ignored trial of F02's test in runs/hwsim-logs/: never evidence.
    f02 = next(r for r in v.rows() if r["id"] == "F02")
    assert f02["runs"] == "3 runs: 1793897820; 1793897968; 1793898029"
    assert "1793948173" not in f02["runs"]


def test_a_run_with_an_unknown_harness_is_never_on_the_frozen_versions():
    ref = v.frozen()
    run = {"harness": None, "hostap_commit": ref["hostap_commit"],
           "kernel_commit": ref["kernel_commit"]}
    assert not v.on_frozen(run, ref)
    assert v.on_frozen({**run, "harness": ref["harness"]}, ref)
    assert not v.on_frozen({**run, "harness": ref["harness"], "kernel_commit": "0"}, ref)


def test_status():
    assert v._status(3, 3, 3) == "VERIFIED"
    assert v._status(4, 4, 3) == "VERIFIED"
    assert v._status(3, 3, 2) == "RERUN"
    assert v._status(0, 0, 0) == "RERUN"
    assert v._status(3, 2, 2) == "FAILED"
    assert v._status(3, 3, 3, ok=False) == "FAILED"


def _contrast_dir(tmp_path, change):
    reduction = json.loads((v.CONTRASTS_DIR / "c1" / "reduction.json").read_text())
    change(reduction)
    (tmp_path / "cx").mkdir(parents=True)
    (tmp_path / "cx" / "reduction.json").write_text(json.dumps(reduction))
    return tmp_path


def test_contrast_status_follows_the_evidence(tmp_path):
    ref = v.frozen()
    status = lambda d, r=ref: [row["status"] for row in v.contrast_rows(r, contrasts_dir=d)]
    assert status(v.CONTRASTS_DIR)[:2] == ["VERIFIED", "VERIFIED"]   # c1 on today's harness
    # Another frozen harness: c1's runs no longer count, so both sides need a rerun.
    assert status(v.CONTRASTS_DIR, {**ref, "harness": "0" * 64})[:2] == ["RERUN", "RERUN"]
    # A side whose run didn't reproduce it fails; the other side is held back too.
    def unreproduced(r):
        r["verification"]["minimal"][0]["matches_target"] = False
    assert status(_contrast_dir(tmp_path / "a", unreproduced)) == ["RERUN", "FAILED"]
    # Only fewer than 3 frozen runs on one side: the other side waits for it.
    def short(r):
        r["verification"]["minimal"] = r["verification"]["minimal"][:2]
    assert status(_contrast_dir(tmp_path / "b", short)) == ["RERUN", "RERUN"]
    def pending(r):
        r["verification"]["label"] = "PENDING_VERIFICATION"
    assert status(_contrast_dir(tmp_path / "c", pending)) == ["FAILED", "FAILED"]
    def superseded(r):
        r["superseded_by"] = "c1"
    assert status(_contrast_dir(tmp_path / "d", superseded)) == []


def test_freeze_json_sets_the_reference(tmp_path, monkeypatch):
    freeze = tmp_path / "freeze.json"
    freeze.write_text(json.dumps({"hostap_commit": "h", "kernel_commit": "k",
                                  "harness": "x", "tag": "checkpoint3-freeze"}))
    monkeypatch.setattr(v, "FREEZE_JSON", freeze)
    assert v.frozen() == {"hostap_commit": "h", "kernel_commit": "k", "harness": "x",
                          "reference": "freeze.json (checkpoint3-freeze)"}
