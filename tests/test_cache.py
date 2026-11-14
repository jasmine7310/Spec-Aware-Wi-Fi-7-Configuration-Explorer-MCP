"""Checks the experiment cache (issue #67): the key covers what decides a run, hits and
misses behave, failures aren't reused, hits aren't independent runs, and the index can be
rebuilt from committed run folders."""

import json
from pathlib import Path

import pytest

from explorer import adapter, cache
from explorer.adapter import CandidateRun
from explorer.cache import Cache, cache_key, key_parts, run_cached
from explorer.model import Candidate
from explorer.model_json import apply


def _candidate(**choices):
    return Candidate.model_validate(apply(choices))


@pytest.fixture
def db(tmp_path):
    c = Cache(tmp_path / "cache.sqlite")
    yield c
    c.close()


@pytest.fixture
def fake_runs(monkeypatch, tmp_path):
    """Replace adapter.run_candidate: each call 'boots a guest', writes a minimal run
    folder with the recorded plan, and returns the status queued in ``outcomes``."""
    calls, outcomes = [], []

    def fake_run_candidate(candidate, *, metadata=None, timeout_s=600, **kwargs):
        calls.append(candidate)
        status = outcomes.pop(0) if outcomes else "ACCEPTED"
        run_id = str(1800000000 + len(calls))
        run_dir = tmp_path / "runs" / run_id
        run_dir.mkdir(parents=True)
        plan = {**adapter.build_plan(candidate),
                "explorer": {**adapter.run_metadata(candidate), "timeout_s": timeout_s,
                             **(metadata or {})}}
        (run_dir / "manifest.json").write_text(json.dumps(
            {"run_id": run_id, "results": [{"test": "explorer_candidate",
                                            "result": "PASS" if status == "ACCEPTED" else "FAIL"}],
             "explorer_plan": plan}))
        return CandidateRun(status=status, reason=None if status == "ACCEPTED" else "x",
                            run_id=run_id, run_dir=run_dir, record=None, plan=plan)

    monkeypatch.setattr(adapter, "run_candidate", fake_run_candidate)
    return calls, outcomes


# --- The key ------------------------------------------------------------------------

def test_key_is_stable_and_readable():
    parts = key_parts(_candidate())
    assert cache_key(parts) == cache_key(key_parts(_candidate()))
    assert cache_key(parts).startswith("sha256:")
    assert set(parts) == {"candidate", "plan", "hostap_commit", "kernel_commit", "environment",
                          "schema_version", "model_digest", "harness"}
    assert parts["hostap_commit"] == "43ee60e13c257d33d25bfb6892b9ee38fb6e88a4"


def test_key_ignores_how_the_input_was_written():
    data = apply({})
    reordered = json.loads(json.dumps(data, sort_keys=True))
    assert cache_key(key_parts(Candidate.model_validate(reordered))) == \
        cache_key(key_parts(Candidate.model_validate(data)))


def test_key_changes_with_the_candidate():
    keys = {cache_key(key_parts(c)) for c in (
        _candidate(), _candidate(ap_pairwise_cipher="GCMP-256"),
        _candidate(rekey_gtk_now="present"), _candidate(sta_sae_pwe="2"))}
    assert len(keys) == 4


def test_key_changes_with_the_environment(tmp_path):
    # A changed Dockerfile (or base image) misses, whatever the local image ID is.
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(cache.DOCKERFILE.read_text() + "\n# rebuilt differently\n")
    base = key_parts(_candidate())
    changed = key_parts(_candidate(), dockerfile=dockerfile)
    assert changed["environment"] != base["environment"]
    assert cache_key(changed) != cache_key(base)


def test_key_changes_with_the_harness(tmp_path):
    files = []
    for f in cache.HARNESS_FILES:
        copy = tmp_path / f.name
        copy.write_bytes(f.read_bytes())
        files.append(copy)
    assert key_parts(_candidate(), harness_files=files)["harness"] == key_parts(_candidate())["harness"]
    files[1].write_text(files[1].read_text() + "\n# changed\n")
    assert cache_key(key_parts(_candidate(), harness_files=files)) != cache_key(key_parts(_candidate()))


def test_key_changes_with_the_model(monkeypatch):
    base = cache_key(key_parts(_candidate()))
    from explorer import model_json
    real = model_json.build()
    monkeypatch.setattr(model_json, "build", lambda: {**real, "model_digest": "sha256:other"})
    assert cache_key(key_parts(_candidate())) != base


# --- Hits and misses ---------------------------------------------------------------

def test_miss_runs_and_records_then_hit_reuses(db, fake_runs):
    calls, _ = fake_runs
    first, run = run_cached(_candidate(rekey_gtk_now="present"), db, context={"seed": 0})
    assert run is not None and len(calls) == 1 and first.independent
    second, run2 = run_cached(_candidate(rekey_gtk_now="present"), db)
    assert run2 is None and len(calls) == 1          # no guest booted
    assert (second.run_id, second.status) == (first.run_id, "ACCEPTED")
    assert second.independent is False               # not a new reproduction
    assert second.context == {"seed": 0}


def test_run_records_its_key_and_context_in_the_manifest(db, fake_runs):
    outcome, run = run_cached(_candidate(), db, context={"campaign": "c1", "seed": 3})
    meta = json.loads((run.run_dir / "manifest.json").read_text())["explorer_plan"]["explorer"]
    assert meta["cache_key"] == outcome.key
    assert meta["context"] == {"campaign": "c1", "seed": 3}
    assert meta["timeout_s"] == 600
    assert meta["cache_key_parts"]["harness"] == key_parts(_candidate())["harness"]


@pytest.mark.parametrize("status", ["SETUP_FAIL", "TIMEOUT"])
def test_failures_are_recorded_but_not_reused(db, fake_runs, status):
    calls, outcomes = fake_runs
    outcomes.extend([status, "ACCEPTED"])
    first, _ = run_cached(_candidate(), db)
    assert first.status == status
    second, run = run_cached(_candidate(), db)       # rerun, not a hit
    assert run is not None and len(calls) == 2 and second.status == "ACCEPTED"
    assert sorted(e["status"] for e in db.entries(first.key)) == sorted([status, "ACCEPTED"])


def test_rejected_is_reused(db, fake_runs):
    calls, outcomes = fake_runs
    outcomes.append("REJECTED")
    run_cached(_candidate(), db)
    hit, run = run_cached(_candidate(), db)
    assert run is None and hit.status == "REJECTED" and len(calls) == 1


def test_force_runs_again_for_an_independent_repeat(db, fake_runs):
    calls, _ = fake_runs
    run_cached(_candidate(), db)
    repeat, run = run_cached(_candidate(), db, force=True)
    assert run is not None and len(calls) == 2 and repeat.independent
    assert len(db.entries(repeat.key)) == 2          # two run IDs: two reproductions


def test_a_changed_environment_misses(db, fake_runs, monkeypatch, tmp_path):
    calls, _ = fake_runs
    run_cached(_candidate(), db)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(cache.DOCKERFILE.read_text() + "\n# other base\n")
    real = cache.key_parts
    monkeypatch.setattr(cache, "key_parts", lambda c: real(c, dockerfile=dockerfile))
    _, run = run_cached(_candidate(), db)
    assert run is not None and len(calls) == 2


# --- Rebuilding the index from committed runs ----------------------------------------

def test_rebuild_indexes_runs_that_recorded_a_key(tmp_path, fake_runs, monkeypatch):
    first_db = Cache(tmp_path / "a.sqlite")
    outcome, run = run_cached(_candidate(ap_pairwise_cipher="GCMP-256"), first_db)
    first_db.close()
    from explorer import signatures
    monkeypatch.setattr(signatures, "extract_record", lambda *a, **k: _Record())
    monkeypatch.setattr(adapter, "classify", lambda *a: ("ACCEPTED", None))
    monkeypatch.setattr(adapter, "comparable_signature", lambda r: {"fact": 1})
    fresh = Cache(tmp_path / "b.sqlite")
    assert fresh.rebuild([tmp_path / "runs"]) == 1
    hit = fresh.lookup(outcome.key)
    assert hit is not None and hit.run_id == run.run_id and not hit.independent
    fresh.close()


class _Record:
    test_result = "PASS"


def test_rebuild_indexes_exactly_the_committed_runs_that_recorded_a_key(tmp_path):
    from explorer.support import EVIDENCE_DIRS
    keyed = [m for d in EVIDENCE_DIRS for m in Path(d).rglob("manifest.json")
             if json.loads(m.read_text()).get("explorer_plan", {}).get("explorer", {}).get("cache_key")]
    db = Cache(tmp_path / "c.sqlite")
    assert db.rebuild(EVIDENCE_DIRS) == len(keyed)    # older runs (no key) are skipped
    db.close()


def test_the_database_is_git_ignored():
    gitignore = (Path(cache.REPO_ROOT) / ".gitignore").read_text()
    assert "runs/cache.sqlite" in gitignore
    assert cache.DEFAULT_DB == Path(cache.REPO_ROOT) / "runs" / "cache.sqlite"
