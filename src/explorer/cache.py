"""Experiment cache (issue #67): don't rerun a candidate that already ran under the same
conditions, and report how many guest boots that saved.

The key (``key_parts`` -> ``cache_key``) is a SHA-256 over everything that decides what a
run does:

- the normalized candidate (config and ordered actions) and the exact plan the guest runs
  (``adapter.build_plan``: hostapd parameters, client arguments, actions);
- the pinned hostap and kernel commits;
- the environment: the pinned base-image digest plus a hash of ``docker/Dockerfile``. Not
  the local image ID, which changed three times in one day on builds entirely from
  Docker's cache;
- the model: ``model.SCHEMA_VERSION`` and ``model.json``'s ``model_digest``;
- the harness: a hash of ``docker/test_eht_client_bp.py``,
  ``docker/test_explorer_candidate.py`` and ``docker/run-test.sh``.

The store is SQLite (``runs/cache.sqlite``, git-ignored). Each run also records its key
in its own ``explorer_plan.json`` and manifest, so ``Cache.rebuild()`` re-indexes the
committed runs (``campaigns/``, ``runs/smoke/``, ...) on any machine; the run folders
stay the evidence, the database is an index of them.

Only ACCEPTED and REJECTED runs are served as hits: they say what the pinned
implementation does with the candidate. SETUP_FAIL and TIMEOUT say nothing about it, so
they're recorded but rerun (the #80 decision). A hit is never a new independent run:
``CachedOutcome.independent`` is False, and repeat counts (anchors, contrasts' 3/3) must
count run IDs, not lookups.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from explorer.model import SCHEMA_VERSION, Candidate

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "runs" / "cache.sqlite"
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"
HARNESS_FILES = [REPO_ROOT / "docker" / name for name in
                 ("test_eht_client_bp.py", "test_explorer_candidate.py", "run-test.sh")]
# Outcomes that say what the implementation does with the candidate; only these are hits.
REUSABLE = ("ACCEPTED", "REJECTED")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _dockerfile_args(dockerfile: Path = DOCKERFILE) -> dict[str, str]:
    return dict(re.findall(r"^ARG (\w+)=(\S+)$", dockerfile.read_text(), re.MULTILINE))


def environment_digest(dockerfile: Path = DOCKERFILE) -> str:
    """The pinned base image (its digest is in the ARG) plus the Dockerfile's contents."""
    args = _dockerfile_args(dockerfile)
    return _sha256(_canonical({"base_image": args["UBUNTU_IMAGE"],
                               "dockerfile": _sha256(dockerfile.read_bytes())}).encode())


def harness_digest(files=HARNESS_FILES) -> str:
    return _sha256(_canonical({Path(f).name: _sha256(Path(f).read_bytes())
                               for f in files}).encode())


def key_parts(candidate: Candidate, dockerfile: Path = DOCKERFILE,
              harness_files=HARNESS_FILES) -> dict:
    """Everything the key covers, readable (stored with each entry)."""
    from explorer.adapter import build_plan
    from explorer.model_json import build
    args = _dockerfile_args(dockerfile)
    return {
        "candidate": candidate.model_dump(mode="json"),
        "plan": build_plan(candidate),
        "hostap_commit": args["HOSTAP_COMMIT"],
        "kernel_commit": args["KERNEL_COMMIT"],
        "environment": environment_digest(dockerfile),
        "schema_version": SCHEMA_VERSION,
        "model_digest": build()["model_digest"],
        "harness": harness_digest(harness_files),
    }


def cache_key(parts: dict) -> str:
    return "sha256:" + _sha256(_canonical(parts).encode())


class CachedOutcome(BaseModel):
    """A stored run outcome. ``independent`` is False when it was served from the cache:
    it's evidence of that earlier run, not a new reproduction."""
    key: str
    run_id: str | None
    status: str
    reason: str | None
    signature: dict | None
    run_dir: str | None
    timeout_s: float | None
    context: dict
    recorded_at: str
    independent: bool = True


class Cache:
    """SQLite store of run outcomes by cache key."""

    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY, key TEXT NOT NULL, status TEXT NOT NULL, reason TEXT,
            signature TEXT, run_dir TEXT, timeout_s REAL, context TEXT NOT NULL,
            key_parts TEXT NOT NULL, recorded_at TEXT NOT NULL)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS runs_by_key ON runs (key)")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def record(self, key: str, parts: dict, *, run_id: str | None, status: str,
               reason: str | None, signature: dict | None, run_dir: str | None,
               timeout_s: float | None, context: dict | None = None) -> CachedOutcome:
        """Store one run's outcome (a run without an ID gets a synthetic one)."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        run_id = run_id or f"no-run-{_sha256((key + now).encode())[:12]}"
        self.db.execute(
            "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, key, status, reason, _canonical(signature) if signature else None,
             run_dir, timeout_s, _canonical(context or {}), _canonical(parts), now))
        self.db.commit()
        return CachedOutcome(key=key, run_id=run_id, status=status, reason=reason,
                             signature=signature, run_dir=run_dir, timeout_s=timeout_s,
                             context=context or {}, recorded_at=now)

    def lookup(self, key: str) -> CachedOutcome | None:
        """The earliest reusable (ACCEPTED / REJECTED) outcome for this key, marked not
        independent; None if there's none."""
        row = self.db.execute(
            "SELECT run_id, status, reason, signature, run_dir, timeout_s, context, recorded_at "
            f"FROM runs WHERE key = ? AND status IN ({','.join('?' * len(REUSABLE))}) "
            "ORDER BY recorded_at, run_id LIMIT 1", (key, *REUSABLE)).fetchone()
        if row is None:
            return None
        run_id, status, reason, signature, run_dir, timeout_s, context, recorded_at = row
        return CachedOutcome(key=key, run_id=run_id, status=status, reason=reason,
                             signature=json.loads(signature) if signature else None,
                             run_dir=run_dir, timeout_s=timeout_s, context=json.loads(context),
                             recorded_at=recorded_at, independent=False)

    def entries(self, key: str | None = None) -> list[dict]:
        query = "SELECT run_id, key, status FROM runs" + (" WHERE key = ?" if key else "")
        return [dict(zip(("run_id", "key", "status"), r))
                for r in self.db.execute(query + " ORDER BY run_id", (key,) if key else ())]

    def rebuild(self, evidence_dirs=None) -> int:
        """Index committed runs that recorded a cache key (``explorer_plan.explorer
        .cache_key`` in their manifest). Returns how many were indexed."""
        from explorer.adapter import ADAPTER_TEST, classify, comparable_signature
        from explorer.signatures import extract_record
        from explorer.support import EVIDENCE_DIRS
        count = 0
        for evidence_dir in (evidence_dirs or EVIDENCE_DIRS):
            for manifest_path in sorted(Path(evidence_dir).rglob("manifest.json")):
                manifest = json.loads(manifest_path.read_text())
                plan = manifest.get("explorer_plan", {})
                meta = plan.get("explorer", {})
                if not meta.get("cache_key"):
                    continue
                run_dir = manifest_path.parent
                record = extract_record(run_dir, ADAPTER_TEST)
                log = run_dir / f"{ADAPTER_TEST}.log"
                status, reason = classify("COMPLETED", record,
                                          log.read_text(errors="replace") if log.exists() else "")
                parts = {**meta.get("cache_key_parts", {}), "candidate": meta["candidate"],
                         "plan": {k: v for k, v in plan.items() if k != "explorer"}}
                self.record(meta["cache_key"], parts,
                            run_id=manifest["run_id"], status=status, reason=reason,
                            signature=comparable_signature(record), run_dir=str(run_dir),
                            timeout_s=meta.get("timeout_s"), context=meta.get("context", {}))
                count += 1
        return count


def run_cached(candidate: Candidate, cache: Cache, *, context: dict | None = None,
               force: bool = False, **run_kwargs):
    """Run ``candidate`` unless an ACCEPTED / REJECTED outcome is cached for its key.

    Returns ``(outcome, run)``: on a hit, the cached outcome and None (no guest booted);
    on a miss, the new outcome (also stored) and the ``adapter.CandidateRun``. ``force``
    runs anyway (e.g. for an independent repeat). ``context`` (campaign, seed, ...) is
    stored with the outcome and recorded in the run's manifest.
    """
    from explorer.adapter import comparable_signature, run_candidate
    parts = key_parts(candidate)
    key = cache_key(parts)
    if not force and (hit := cache.lookup(key)) is not None:
        return hit, None
    metadata = {"cache_key": key, "cache_key_parts": {k: v for k, v in parts.items()
                                                      if k not in ("candidate", "plan")},
                "context": context or {}}
    run = run_candidate(candidate, metadata=metadata, **run_kwargs)
    outcome = cache.record(
        key, parts, run_id=run.run_id, status=run.status, reason=run.reason,
        signature=comparable_signature(run.record) if run.record else None,
        run_dir=str(run.run_dir) if run.run_dir else None,
        timeout_s=run.plan["explorer"].get("timeout_s"), context=context)
    return outcome, run
