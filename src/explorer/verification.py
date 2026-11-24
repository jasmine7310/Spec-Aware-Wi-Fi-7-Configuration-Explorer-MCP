"""Final verification of the anchors and contrasts (issue #116).

``final_verification.csv`` has one row per anchor family (``anchor_coverage.csv``) and one
per side of each minimized contrast (``contrasts/<id>/reduction.json``), with the runs that
verify it. Every column is generated:

- ``runs``: for an anchor, every committed run of the family's own hostap test
  (``source_test``) in the evidence folders (``EVIDENCE_DIRS``: never ``runs/hwsim-logs/``);
  for a contrast side, the side's reproduction runs from the reduction's ``verification``
  (side A is the baseline candidate, side B the baseline with the minimal deltas);
- ``passing_runs``: how many of them passed: the test ``PASS`` for an anchor; for a contrast
  side, ``ACCEPTED`` and reproducing its side as ``minimize.verify`` recorded it (A differs
  from the target facts, B matches them);
- ``frozen_runs``: how many passing runs ran on the frozen versions (``frozen()``): the
  pinned hostap and kernel commits and the frozen harness (``contrasts.run_harness``). A
  run whose harness isn't known (it ran with ``docker/`` modified) is never on it;
- ``harnesses``: the passing runs' harnesses, as ``<first 12 hex> xN`` or ``unknown xN``;
- ``status``: ``VERIFIED`` (at least ``REQUIRED_RUNS`` frozen passing runs; for a contrast,
  both sides, and the reduction is ``MINIMIZED``), ``RERUN`` (fewer frozen passing runs than
  that: run it on the frozen versions) or ``FAILED`` (a listed run didn't pass, or the
  reduction isn't ``MINIMIZED``);
- ``reference``: what "frozen" means here: ``freeze.json`` once #114 commits it, else the
  repo's current pins and harness.

Independence: a run counts once, by its run ID, and only with a committed run folder. A
cache hit never makes a new folder, and ``minimize.verify`` refuses cache hits, so each
counted run is its own fresh guest. Anchor runs are hostap's own tests, contrast runs are
adapter runs, so no run counts for both.

``scripts/update_verification.py`` rewrites the file; ``tests/test_verification.py`` fails
when it's stale.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFICATION_CSV = REPO_ROOT / "final_verification.csv"
FREEZE_JSON = REPO_ROOT / "freeze.json"
CONTRASTS_DIR = REPO_ROOT / "contrasts"
EVIDENCE_DIRS = tuple(REPO_ROOT / "runs" / d for d in
                      ("baseline", "calibration", "smoke", "anchors"))
CONTRAST_RUN_DIRS = (CONTRASTS_DIR / "runs",)
REQUIRED_RUNS = 3
COLUMNS = ("kind", "id", "name", "source", "runs", "passing_runs", "frozen_runs",
           "harnesses", "status", "reference")
STATUSES = ("VERIFIED", "RERUN", "FAILED")
# Side A is the reduction's baseline, side B the baseline with the minimal deltas.
SIDES = (("A", "baseline", False), ("B", "minimal", True))


def frozen() -> dict[str, str]:
    """The versions runs must have: ``freeze.json``'s (#114) if committed, else today's."""
    if FREEZE_JSON.exists():
        data = json.loads(FREEZE_JSON.read_text())
        return {"hostap_commit": data["hostap_commit"], "kernel_commit": data["kernel_commit"],
                "harness": data["harness"],
                "reference": f"freeze.json ({data.get('tag', 'untagged')})"}
    from explorer.cache import harness_digest
    from explorer.model_json import pinned_versions
    pins = pinned_versions()
    return {"hostap_commit": pins["hostap_commit"], "kernel_commit": pins["kernel_commit"],
            "harness": harness_digest(), "reference": "current repo (no freeze.json yet)"}


def _manifests(dirs) -> dict[str, Path]:
    """Run ID -> its committed run folder's manifest."""
    out = {}
    for d in dirs:
        for manifest in sorted(Path(d).rglob("manifest.json")):
            out.setdefault(manifest.parent.name, manifest)
    return out


def _run(manifest: Path) -> dict:
    from explorer.contrasts import run_harness
    data = json.loads(manifest.read_text())
    versions = data.get("versions", {})
    return {"data": data, "harness": run_harness(data),
            "hostap_commit": versions.get("hostap_commit"),
            "kernel_commit": versions.get("kernel_commit")}


def on_frozen(run: dict, ref: dict) -> bool:
    return (run["harness"] is not None and run["harness"] == ref["harness"]
            and run["hostap_commit"] == ref["hostap_commit"]
            and run["kernel_commit"] == ref["kernel_commit"])


def _harnesses(runs: list[dict]) -> str:
    counts = Counter((r["harness"] or "unknown")[:12] for r in runs)
    return "; ".join(f"{h} x{n}" for h, n in sorted(counts.items()))


def _ids(run_ids: list[str]) -> str:
    return f"{len(run_ids)} runs: " + "; ".join(run_ids) if run_ids else "0 runs"


def _status(listed: int, passing: int, frozen_count: int, ok: bool = True) -> str:
    if not ok or passing < listed:
        return "FAILED"
    return "VERIFIED" if frozen_count >= REQUIRED_RUNS else "RERUN"


def anchor_rows(ref: dict, dirs=EVIDENCE_DIRS) -> list[dict[str, str]]:
    from explorer.anchors import rows as anchor_csv
    manifests = _manifests(dirs)
    _, families = anchor_csv()
    out = []
    for family in families:
        test = family["source_test"]
        found = []
        for run_id, manifest in sorted(manifests.items()):
            run = _run(manifest)
            results = [r for r in run["data"].get("results", []) if r["test"] == test]
            if results:
                found.append((run_id, run, all(r["result"] == "PASS" for r in results)))
        passing = [run for _, run, ok in found if ok]
        frozen_count = sum(on_frozen(run, ref) for run in passing)
        out.append({
            "kind": "anchor", "id": family["family_id"], "name": family["name"],
            "source": test, "runs": _ids([run_id for run_id, _, _ in found]),
            "passing_runs": str(len(passing)), "frozen_runs": str(frozen_count),
            "harnesses": _harnesses(passing),
            "status": _status(len(found), len(passing), frozen_count),
            "reference": ref["reference"]})
    return out


def reductions(contrasts_dir: Path = CONTRASTS_DIR) -> list[tuple[str, dict]]:
    """(id, reduction) for each current minimized contrast: ``contrasts/<id>/reduction.json``
    one level down (a nested one is a superseded attempt)."""
    out = []
    for path in sorted(Path(contrasts_dir).glob("*/reduction.json")):
        data = json.loads(path.read_text())
        if not data.get("superseded_by"):
            out.append((path.parent.name, data))
    return out


def contrast_rows(ref: dict, dirs=CONTRAST_RUN_DIRS,
                  contrasts_dir: Path = CONTRASTS_DIR) -> list[dict[str, str]]:
    manifests = _manifests(dirs)
    out = []
    for cid, reduction in reductions(contrasts_dir):
        verification = reduction.get("verification") or {}
        minimized = verification.get("label") == "MINIMIZED"
        targets = ", ".join(reduction.get("target_facts", []))
        sides = []
        for side, key, matches in SIDES:
            entries = verification.get(key, [])
            passing = []
            for entry in entries:
                manifest = manifests.get(entry["run_id"])
                if (manifest and entry.get("status") == "ACCEPTED"
                        and entry.get("matches_target") is matches):
                    passing.append(_run(manifest))
            sides.append((side, key, entries, passing,
                          sum(on_frozen(run, ref) for run in passing)))
        both = all(frozen_count >= REQUIRED_RUNS for *_, frozen_count in sides)
        for side, key, entries, passing, frozen_count in sides:
            status = _status(len(entries), len(passing), frozen_count, minimized)
            if status == "VERIFIED" and not both:
                status = "RERUN"   # the other side isn't on the frozen versions yet
            out.append({
                "kind": "contrast_side", "id": f"{cid}:{side}",
                "name": f"{cid} side {side} ({'differs from' if side == 'A' else 'matches'} "
                        f"target {targets})",
                "source": f"reduction.json verification.{key}",
                "runs": _ids([e["run_id"] for e in entries]),
                "passing_runs": str(len(passing)), "frozen_runs": str(frozen_count),
                "harnesses": _harnesses(passing), "status": status,
                "reference": ref["reference"]})
    return out


def verification_rows() -> list[dict[str, str]]:
    ref = frozen()
    return anchor_rows(ref) + contrast_rows(ref)


def render() -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(verification_rows())
    return buf.getvalue()


def rows(path: Path = VERIFICATION_CSV) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(path: Path = VERIFICATION_CSV) -> None:
    Path(path).write_text(render(), encoding="utf-8")
