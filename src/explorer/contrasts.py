"""Accepted-vs-accepted contrasts (issue #71): two legal candidates whose runs both came
back ``ACCEPTED`` but show different observable behavior.

Sides are committed adapter runs (``campaigns/`` and ``contrasts/runs/``) that

- came back ``ACCEPTED`` (``adapter.classify`` on the run's own log), so infrastructure
  failures (``SETUP_FAIL`` / ``TIMEOUT``) and refusals (``REJECTED``) are never sides;
- aren't negative experiments and still pass today's modeled rules
  (``support.passes_current_rules``), so a spec-forbidden candidate is never a side;
- ran on the pinned hostap / kernel commits under a compatible schema version;
- ran under a known harness (``run_harness``: the adapter test and run script in
  ``docker/``), since a harness change can change what a run logs.

Runs of the same candidate under the same harness are grouped: they're repeats. A
contrast is a pair of such groups, under the same harness and both P2 ``SUPPORTED``
(``support.check_support``), at most ``max_inputs`` inputs apart (``input_diff`` /
``distance``: each differing config value and each action step only one side performs
counts once) with at least one **claimable** fact difference:

- measured on both sides: never ``UNKNOWN`` (``signatures`` sets a fact to ``UNKNOWN``
  when the log doesn't show it);
- stable within each side: every repeat of a candidate has the same value, otherwise the
  fact is reported as unstable and claims nothing;
- different between the sides.

Facts are the behavior record's signature without the test name
(``adapter.comparable_signature``), plus ``disconnect_reasons``: the set of
(reason, locally_generated) in ``disconnects``, which stays the same when only the number
or order of identical disconnects varies between repeats. Each claimed fact comes with the
log lines it was read from (``evidence``), so no claim goes beyond what the logs show.
``reproduced`` is true only when both sides have at least ``REPRODUCE_RUNS`` runs.
``current_harness`` says whether the runs used today's harness (``cache.harness_digest``).

Each contrast has a stable ``id`` (``contrast_id``): a hash of its two candidates and
harness, so it doesn't shift when contrasts are added or a side gets more repeats (#111).
Each pair has a fixed orientation (A's candidate sorts first as canonical JSON), so the
read order of the run folders never swaps the sides or changes the ID.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from explorer import signatures
from explorer.signatures import UNKNOWN

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRASTS_DIR = REPO_ROOT / "contrasts"
SIDE_DIRS = (REPO_ROOT / "campaigns", CONTRASTS_DIR / "runs")
REPRODUCE_RUNS = 3
"""Runs per side for a contrast to count as reproduced (the roadmap's 3/3)."""
MAX_EVIDENCE_LINES = 4

# Fact -> the signatures pattern its value is read from, and whether it's the last match
# (a last-value fact) or every match (a count or a list).
_EVIDENCE = {
    "association_succeeded": (signatures._CONNECTED, False),
    "valid_links": (re.compile(r"INFO valid_links="), True),
    "active_links": (re.compile(r"INFO active_links="), True),
    "data_test_rx_ap_links": (signatures._DATA_RX, False),
    "four_way_handshakes_completed": (signatures._FOUR_WAY, False),
    "disconnects": (signatures._DISCONNECTED, False),
    "disconnect_reasons": (signatures._DISCONNECTED, False),
    "station_status": (signatures._STATUS, True),
    "ptk_rekeys_completed": (signatures._PTK_NEGOTIATED, False),
    "gtk_rekeys_completed": (signatures._GTK_REKEYED, False),
    "link_reconfig_valid_links": (signatures._LINK_RECONFIG, False),
}


class Run(BaseModel):
    run_id: str
    folder: str
    """Repo-relative run folder."""
    facts: dict[str, Any]
    harness: str | None = None
    """The harness hash the run ran under (``run_harness``)."""


class Group(BaseModel):
    """Every accepted run of one candidate under one harness."""
    candidate: dict
    runs: list[Run]
    harness: str | None = None


class FactDiff(BaseModel):
    fact: str
    a: Any
    b: Any
    evidence_a: list[str]
    """Log lines the value was read from, in the first run of side A ("file:line: text")."""
    evidence_b: list[str]


class Contrast(BaseModel):
    id: str
    """Stable ID (``contrast_id``): the same for the same two candidates and harness."""
    a_runs: list[str]
    b_runs: list[str]
    input_diff: dict[str, list[Any]]
    """Flattened candidate path -> [A's value, B's value]."""
    facts: list[FactDiff]
    """Claimable differences: measured on both sides, stable within each, different."""
    unstable: list[str]
    """Facts that differ between repeats of one side; nothing is claimed about them."""
    reproduced: bool
    """Both sides have at least REPRODUCE_RUNS runs (and the claimed facts held in each)."""
    harness: str | None
    """The harness hash both sides ran under."""
    current_harness: bool
    """That harness is today's (``cache.harness_digest()``)."""
    candidate_a: dict
    candidate_b: dict


def facts(signature: dict) -> dict[str, Any]:
    """The comparable facts of one run: the signature without the test name, plus
    ``disconnect_reasons``."""
    out = {k: v for k, v in signature.items() if k != "test"}
    disconnects = out.get("disconnects", UNKNOWN)
    out["disconnect_reasons"] = (UNKNOWN if disconnects == UNKNOWN else sorted(
        {(d["reason"], d["locally_generated"]) for d in disconnects}))
    return json.loads(json.dumps(out))  # tuples -> lists, so values compare as stored


def _folder(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def run_harness(manifest: dict) -> str | None:
    """The harness hash a run ran under: the one recorded with its cache key or, for a
    run that didn't record one, that of the repo commit it ran from, if ``docker/`` was
    unmodified then. None when neither is known."""
    from explorer.cache import harness_digest_at
    parts = manifest.get("explorer_plan", {}).get("explorer", {}).get("cache_key_parts") or {}
    if parts.get("harness"):
        return parts["harness"]
    versions = manifest.get("versions", {})
    if versions.get("repo_commit") and versions.get("repo_docker_dir_modified") is False:
        return harness_digest_at(versions["repo_commit"])
    return None


def accepted_runs(dirs=SIDE_DIRS) -> list[tuple[dict, Run]]:
    """(candidate, run) for every committed adapter run that may be a side (module
    docstring)."""
    from explorer.adapter import ADAPTER_TEST, classify, comparable_signature
    from explorer.support import (RecordedRun, _on_pinned_versions, _parse,
                                  passes_current_rules)
    out = []
    for d in dirs:
        for manifest_path in sorted(Path(d).rglob("manifest.json")):
            manifest = json.loads(manifest_path.read_text())
            meta = manifest.get("explorer_plan", {}).get("explorer")
            if not meta or meta.get("negative_experiment"):
                continue
            if not any(r["test"] == ADAPTER_TEST for r in manifest["results"]):
                continue
            harness = run_harness(manifest)
            if harness is None:
                continue
            run_dir = manifest_path.parent
            versions = manifest.get("versions", {})
            recorded = RecordedRun(candidate=meta["candidate"],
                                   hostap_commit=versions.get("hostap_commit"),
                                   kernel_commit=versions.get("kernel_commit"),
                                   schema_version=meta.get("schema_version"))
            parsed = _parse(recorded)
            if parsed is None or not _on_pinned_versions(recorded) \
                    or not passes_current_rules(parsed):
                continue
            record = signatures.extract_record(run_dir, ADAPTER_TEST)
            log = run_dir / f"{ADAPTER_TEST}.log"
            status, _ = classify("COMPLETED", record,
                                 log.read_text(errors="replace") if log.exists() else "")
            if status != "ACCEPTED":
                continue
            out.append((meta["candidate"], Run(run_id=manifest["run_id"],
                                               folder=_folder(run_dir),
                                               facts=facts(comparable_signature(record)),
                                               harness=harness)))
    return out


def group(runs: list[tuple[dict, Run]]) -> list[Group]:
    """Runs grouped by identical candidate and harness, in first-seen order."""
    groups: dict[str, Group] = {}
    for candidate, run in runs:
        key = json.dumps([candidate, run.harness], sort_keys=True)
        groups.setdefault(key, Group(candidate=candidate, runs=[],
                                     harness=run.harness)).runs.append(run)
    return list(groups.values())


@lru_cache(maxsize=None)
def _supported(candidate_json: str) -> bool:
    from explorer.model import Candidate
    from explorer.support import check_support
    candidate = Candidate.model_validate(json.loads(candidate_json))
    return check_support(candidate).status == "SUPPORTED"


def p2_supported(candidate: dict) -> bool:
    """Whether P2 (``support.check_support``) says ``SUPPORTED`` for the candidate."""
    return _supported(json.dumps(candidate, sort_keys=True))


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{path}.{key}" if path else key))
        return out
    if isinstance(value, list) and path.endswith("links"):
        out = {}
        for i, item in enumerate(value):
            out.update(_flatten(item, f"{path}[{i}]"))
        return out
    return {path: value}


def input_diff(a: dict, b: dict) -> dict[str, list[Any]]:
    """Inputs that differ between two candidates: the config flattened (per AP link), and
    for the actions, the steps only one side performs (``actions``: [A's, B's]) or, when
    both perform the same steps, the two orders (``actions order``)."""
    fa, fb = _flatten(a.get("config", {})), _flatten(b.get("config", {}))
    diff = {f"config.{k}": [fa.get(k), fb.get(k)] for k in sorted(set(fa) | set(fb))
            if fa.get(k) != fb.get(k)}
    steps_a, steps_b = a.get("actions", []), b.get("actions", [])
    if steps_a != steps_b:
        only_a, rest_b = [], list(steps_b)
        for step in steps_a:
            if step in rest_b:
                rest_b.remove(step)
            else:
                only_a.append(step)
        if only_a or rest_b:
            diff["actions"] = [only_a, rest_b]
        else:
            diff["actions order"] = [steps_a, steps_b]
    return diff


def distance(diff: dict[str, list[Any]]) -> int:
    """How many inputs differ: each config value, each action step only one side performs,
    and a reordering of the same steps as one."""
    n = sum(1 for k in diff if k.startswith("config."))
    if "actions" in diff:
        n += len(diff["actions"][0]) + len(diff["actions"][1])
    return n + ("actions order" in diff)


def _stable(group: Group, fact: str) -> tuple[bool, Any]:
    values = [json.dumps(r.facts[fact], sort_keys=True) for r in group.runs]
    return len(set(values)) == 1, group.runs[0].facts[fact]


def evidence(run_folder: str, fact: str, limit: int = MAX_EVIDENCE_LINES) -> list[str]:
    """The adapter log lines a fact's value is read from ("folder/file:line: text")."""
    from explorer.adapter import ADAPTER_TEST
    pattern, last = _EVIDENCE.get(fact, (None, False))
    log = REPO_ROOT / run_folder / f"{ADAPTER_TEST}.log"
    if pattern is None or not log.exists():
        return []
    hits = [f"{run_folder}/{log.name}:{n}: {line.strip()[:200]}"
            for n, line in enumerate(log.read_text(errors="replace").splitlines(), 1)
            if pattern.search(line)]
    return hits[-1:] if last else hits[:limit]


def compare(a: Group, b: Group) -> tuple[list[FactDiff], list[str]]:
    """Claimable fact differences between two groups, and the unstable facts."""
    diffs, unstable = [], []
    for fact in a.runs[0].facts:
        stable_a, va = _stable(a, fact)
        stable_b, vb = _stable(b, fact)
        if not (stable_a and stable_b):
            unstable.append(fact)
            continue
        if UNKNOWN in (va, vb) or va == vb:
            continue
        diffs.append(FactDiff(fact=fact, a=va, b=vb,
                              evidence_a=evidence(a.runs[0].folder, fact),
                              evidence_b=evidence(b.runs[0].folder, fact)))
    return diffs, unstable


def _canonical(candidate: dict) -> str:
    return json.dumps(candidate, sort_keys=True)


def contrast_id(candidate_a: dict, candidate_b: dict, harness: str | None) -> str:
    """A contrast's stable ID: ``x`` and 10 hex digits of the hash of its two candidates
    (in canonical order, so the ID doesn't depend on which side is A) and harness. Unlike a
    list index it doesn't change when contrasts are added, and unlike run IDs it doesn't
    change when a side gets more repeats."""
    first, second = sorted([_canonical(candidate_a), _canonical(candidate_b)])
    blob = json.dumps([json.loads(first), json.loads(second), harness], sort_keys=True)
    return "x" + hashlib.sha256(blob.encode()).hexdigest()[:10]


def find(groups: list[Group], max_inputs: int = 1,
         supported: Callable[[dict], bool] = p2_supported) -> list[Contrast]:
    """Every pair of groups under the same harness, both ``supported``, at most
    ``max_inputs`` inputs apart with a claimable fact difference: today's harness first,
    then the most-repeated pairs."""
    from explorer.cache import harness_digest
    current = harness_digest()
    out = []
    for a, b in itertools.combinations(groups, 2):
        if a.harness != b.harness:
            continue
        # A fixed orientation: A is the side whose candidate's canonical JSON sorts first,
        # so neither the ID nor which side is A depends on the order runs were read in.
        if _canonical(a.candidate) > _canonical(b.candidate):
            a, b = b, a
        diff = input_diff(a.candidate, b.candidate)
        if not 0 < distance(diff) <= max_inputs:
            continue
        facts_, unstable = compare(a, b)
        if not facts_ or not (supported(a.candidate) and supported(b.candidate)):
            continue
        out.append(Contrast(
            id=contrast_id(a.candidate, b.candidate, a.harness),
            a_runs=[r.run_id for r in a.runs], b_runs=[r.run_id for r in b.runs],
            input_diff=diff, facts=facts_, unstable=unstable,
            reproduced=min(len(a.runs), len(b.runs)) >= REPRODUCE_RUNS,
            harness=a.harness, current_harness=a.harness == current,
            candidate_a=a.candidate, candidate_b=b.candidate))
    return sorted(out, key=lambda c: (not c.current_harness,
                                      -min(len(c.a_runs), len(c.b_runs)),
                                      distance(c.input_diff), c.a_runs[0], c.b_runs[0]))


CONTRASTS_JSON = CONTRASTS_DIR / "contrasts.json"
DEFAULT_MAX_INPUTS = 1


def build(max_inputs: int = DEFAULT_MAX_INPUTS, dirs=SIDE_DIRS) -> dict:
    """contrasts.json's content: every contrast within ``max_inputs`` among the committed
    accepted runs."""
    runs = accepted_runs(dirs)
    groups = group(runs)
    found = find(groups, max_inputs)
    from explorer.cache import harness_digest
    return {
        "description": ("Accepted-vs-accepted contrasts (issue #71), generated by "
                        "scripts/find_contrasts.py from committed adapter runs. Both sides "
                        "are P2 SUPPORTED and ran under the same harness; only facts "
                        "measured on both sides and stable across each side's repeats are "
                        "claimed; contrasts/README.md writes the chosen ones up."),
        "current_harness": harness_digest(),
        "max_inputs": max_inputs,
        "reproduce_runs": REPRODUCE_RUNS,
        "side_dirs": [_folder(Path(d)) for d in dirs],
        "accepted_runs": len(runs),
        "candidates": len(groups),
        "contrasts": [c.model_dump(mode="json") for c in found],
    }


def write(max_inputs: int = DEFAULT_MAX_INPUTS) -> dict:
    data = build(max_inputs)
    CONTRASTS_DIR.mkdir(exist_ok=True)
    CONTRASTS_JSON.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return data
