"""The version freeze before the held-out campaign (issue #114).

A held-out result only counts if the rules, the model, the harness and the pinned
versions it ran on didn't change after the freeze. ``freeze.json`` (repo root) records
them, written by ``scripts/freeze_versions.py --tag <tag>`` right before the repo is
tagged and before any held-out result is looked at:

- ``rules_sha256``: ``rules.yaml``'s content (line endings normalized);
- ``model_digest`` and ``schema_version``: ``model.json``'s, as ``model_json.build()``
  gives them today;
- ``harness``: ``cache.harness_digest()``, the adapter test and run script in ``docker/``;
- ``hostap_commit``, ``kernel_commit``, ``base_image``: the Dockerfile's pins;
- ``code_sha256``: the pipeline code that applies the rules and runs the campaign
  (``CODE_FILES``: P0 in ``model``, P1 in ``validate`` and ``config_space``, P2 in
  ``support``, the planner, the adapter, the runner, signatures and contrasts, and the two
  campaign scripts), line endings normalized. ``rules_sha256`` alone wouldn't show a
  change to how a rule is checked (decided on PR #125). The rest of ``src/explorer/``
  (MCP server, minimization, metrics, reports) can change after the freeze.

``differences`` lists what no longer matches. ``tests/test_freeze.py`` runs it against the
committed ``freeze.json`` when there is one, so a rule, model or pipeline-code change after
the freeze fails the tests: the held-out campaign then has to be rerun, as #114 says.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FREEZE_JSON = REPO_ROOT / "freeze.json"
RULES_YAML = REPO_ROOT / "rules.yaml"
PIPELINE_MODULES = ("adapter", "cache", "campaign", "config_space", "contrasts", "model",
                    "model_json", "planner", "rules", "runner", "scenarios", "signatures",
                    "support", "validate")
"""``planner`` and ``campaign`` and every ``explorer`` module they import, directly or
not (``tests/test_freeze.py`` checks the list stays closed under imports)."""
CODE_FILES = tuple(f"src/explorer/{name}.py" for name in PIPELINE_MODULES) + (
    "scripts/plan_campaign.py", "scripts/run_campaign.py")
FROZEN_KEYS = ("rules_sha256", "model_digest", "schema_version", "harness",
               "hostap_commit", "kernel_commit", "base_image", "code_sha256")


def code_digest(files=CODE_FILES, root: Path = REPO_ROOT) -> str:
    """sha256 over each file's path and content (line endings normalized)."""
    parts = {f: hashlib.sha256((root / f).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
             for f in files}
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def current() -> dict:
    """The frozen quantities as the repo has them now."""
    from explorer import model_json
    from explorer.cache import harness_digest
    model = model_json.build()
    rules = RULES_YAML.read_bytes().replace(b"\r\n", b"\n")
    pins = model_json.pinned_versions()
    return {"rules_sha256": hashlib.sha256(rules).hexdigest(),
            "model_digest": model["model_digest"],
            "schema_version": model["schema_version"],
            "harness": harness_digest(),
            "hostap_commit": pins["hostap_commit"], "kernel_commit": pins["kernel_commit"],
            "base_image": pins["base_image"],
            "code_sha256": code_digest()}


def differences(frozen: dict, now: dict | None = None) -> list[str]:
    """The frozen quantities that changed, as 'key: frozen -> now'."""
    now = current() if now is None else now
    return [f"{key}: {frozen.get(key)} -> {now.get(key)}" for key in FROZEN_KEYS
            if frozen.get(key) != now.get(key)]


def _git_head() -> str | None:
    done = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def write(tag: str, path: Path = FREEZE_JSON) -> dict:
    """Record the freeze (``current()`` plus the tag, the time and the commit it was
    made on) and return it."""
    data = {**current(), "tag": tag, "git_commit": _git_head(),
            "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "description": ("Versions frozen before the held-out campaign (#114). A change "
                            "to any of " + ", ".join(FROZEN_KEYS) + " after this means the "
                            "campaign is no longer held-out: rerun it.")}
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return data
