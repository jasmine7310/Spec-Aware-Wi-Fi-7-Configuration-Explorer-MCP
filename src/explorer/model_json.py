"""``model.json`` (issue #65): the machine-readable, versioned candidate space.

``build()`` assembles it from the sources that define the space, and
``scripts/build_model_json.py`` writes it to the repo root; ``tests/test_model_json.py``
fails when the file is out of date. What it holds:

- ``candidate_schema``: the P0 model (``model.Candidate``) as JSON Schema: every field,
  type, allowed value, range and default.
- ``dimensions``: the admitted executable dimensions, i.e. ``surface_candidates.csv`` rows
  with at least two smoke-tested values (``docs/dimensions.md``). Each value is given as
  its CSV label, the typed value ``apply()`` puts into a candidate, and the committed run
  that shows it executes. ``rule_ids`` are the rules and open questions whose
  ``applies_to`` names the dimension.
- ``not_admitted``: the other configuration and action rows, documented but not offered.
- ``constraints``: every rule in ``rules.yaml`` with its role (``forbidden`` for
  normative / guidance rules, ``dependency``, ``action_order`` for AO.* rules), whether it
  is coded, and its predicate; ``open_questions``: the UND.* questions.
- ``actions``: the action catalog, with the fields each takes and whether the candidate
  adapter can run it.
- ``pinned_versions``, ``schema_version`` (``model.SCHEMA_VERSION``), ``rules_version``
  (``rules.yaml``'s ``version``) and ``model_digest``.

``model_digest`` hashes everything that defines the space (schema, dimensions' typed
values, constraints, actions, versions) but not the evidence (smoke run IDs) or this
file's own metadata, so recording a new run doesn't change it; changing a value, a rule
or a pinned version does. Run records carry it (``adapter.run_metadata``) and the
experiment cache (#67) can key on it.

``configspace`` summarizes the ConfigSpace encoding of the static settings
(``explorer.config_space``, issue #63): its hyperparameters, each condition and forbidden
clause with the rule it encodes, and the rules left to P1 predicates, with the reason.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from explorer.model import SCHEMA_VERSION, Candidate
from explorer.rules import load_rules

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_JSON = REPO_ROOT / "model.json"
SURFACE_CSV = REPO_ROOT / "surface_candidates.csv"
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"

# The legal F02 candidate (eht_mld_sae_ext_two_links_client_bp) that the smoke runs vary
# one dimension of; apply() starts from it unless given another base.
BASE_TEST = "eht_mld_sae_ext_two_links_client_bp"

_DISABLE_ENABLE = [  # hostap's order, test_eht.py:727-760 (docs/dimensions.md, row 10)
    {"action": "disable_enable_mld", "command": "DISABLE_MLD"},
    {"action": "sta_disconnect_reconnect", "command": "DISCONNECT"},
    {"action": "disable_enable_mld", "command": "ENABLE_MLD"},
    {"action": "sta_disconnect_reconnect", "command": "RECONNECT"},
]
_SAE_PWE = {"unset": None, "1": "hash_to_element", "2": "both"}

# Where each admitted dimension lives in a candidate, and the typed value of each CSV
# label. "config.ap.links[*].x" sets x on every link; "actions" appends the steps after
# the base candidate's actions (an associate). Labels must match surface_candidates.csv.
DIMENSIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "ap_akm": ("config.ap.links[*].akms",
               {"SAE-EXT-KEY": ["SAE-EXT-KEY"], "OWE": ["OWE"]}),
    "sta_akm": ("config.sta.akms", {"SAE-EXT-KEY": ["SAE-EXT-KEY"], "OWE": ["OWE"]}),
    "ap_sae_pwe": ("config.ap.sae_pwe", _SAE_PWE),
    "sta_sae_pwe": ("config.sta.sae_pwe", _SAE_PWE),
    "ap_pairwise_cipher": ("config.ap.links[*].pairwise_cipher",
                           {"CCMP": "CCMP", "GCMP-256": "GCMP-256"}),
    "ap_link_indicate_disabled": ("config.ap.links[1].indicate_disabled",
                                  {"0": False, "1": True}),
    "ap_ptk_rekey_interval": ("config.ap.ptk_rekey_interval_s", {"unset": None, "5": 5}),
    "ap_gtk_rekey_interval": ("config.ap.gtk_rekey_interval_s", {"unset": None, "5": 5}),
    # LINK_REMOVE 4 on link 1, hostap's first removal (test_eht.py:1400).
    "link_remove": ("actions", {"absent": [],
                                "present": [{"action": "link_remove", "link_id": 1,
                                             "count": 4}]}),
    "rekey_gtk_now": ("actions", {"absent": [], "present": [{"action": "rekey_gtk_now"}]}),
    "disable_enable_mld": ("actions", {"absent": [], "present": _DISABLE_ENABLE}),
}

_SMOKE_ENTRY = re.compile(r"^(?P<value>[^=]+)=(?P<run_id>\d+)$")


def _surface_rows() -> list[dict[str, str]]:
    with SURFACE_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _smoke_runs(row: dict[str, str]) -> dict[str, str]:
    entries = [_SMOKE_ENTRY.match(e.strip()) for e in row["smoke_runs"].split(";") if e.strip()]
    return {m["value"]: m["run_id"] for m in entries if m}


def admitted_rows() -> list[dict[str, str]]:
    """surface_candidates.csv rows with at least two smoke-tested values."""
    return [row for row in _surface_rows() if len(_smoke_runs(row)) >= 2]


def pinned_versions() -> dict[str, str]:
    args = dict(re.findall(r"^ARG (\w+)=(\S+)$", DOCKERFILE.read_text(), re.MULTILINE))
    return {"hostap_commit": args["HOSTAP_COMMIT"], "kernel_commit": args["KERNEL_COMMIT"],
            "base_image": args["UBUNTU_IMAGE"]}


def base_candidate() -> dict:
    from explorer.scenarios import TEST_CANDIDATES  # scenarios imports model only
    return TEST_CANDIDATES[BASE_TEST].model_dump(mode="json")


def apply(choices: dict[str, str], base: dict | None = None) -> dict:
    """The candidate (as JSON data) that sets each dimension in ``choices`` (name -> CSV
    label) on ``base`` (default: the F02 candidate). Raises KeyError for an unknown
    dimension or label. P0/P1 aren't checked here; validate the result."""
    candidate = copy.deepcopy(base if base is not None else base_candidate())
    for name, label in choices.items():
        path, values = DIMENSIONS[name]
        value = copy.deepcopy(values[label])
        if path == "actions":
            candidate["actions"].extend(value)
            continue
        parts = path.split(".")[1:]           # drop "config"
        target = candidate["config"]
        for part in parts[:-1]:
            if part == "links[*]":
                targets = target["links"]
                break
            if m := re.fullmatch(r"links\[(\d+)\]", part):
                target = target["links"][int(m[1])]
            else:
                target = target[part]
        else:
            targets = [target]
        for item in targets:
            item[parts[-1]] = copy.deepcopy(value)
    return candidate


def _dimensions(rule_ids_by_name: dict[str, list[str]]) -> list[dict]:
    out = []
    for row in admitted_rows():
        path, values = DIMENSIONS[row["name"]]
        runs = _smoke_runs(row)
        out.append({
            "name": row["name"],
            "category": row["category"],
            "kind": row["kind"],
            "side": row["side"],
            "path": path,
            "values": [{"label": label, "value": values[label], "smoke_run": run_id}
                       for label, run_id in runs.items()],
            "rule_ids": rule_ids_by_name.get(row["name"], []),
        })
    return out


def _role(rule) -> str:
    if rule.id.startswith("AO."):
        return "action_order"
    return "dependency" if rule.kind == "dependency" else "forbidden"


def _constraints() -> tuple[list[dict], list[dict]]:
    from explorer.validate import P1_CHECKS  # validate imports support -> scenarios
    registry = load_rules()
    constraints = [{
        "id": rule.id,
        "kind": rule.kind,
        "role": _role(rule),
        "status": rule.status,
        "coded": rule.id in P1_CHECKS or rule.id.startswith("AO."),
        "applies_to": rule.applies_to,
        "predicate": rule.predicate,
    } for rule in registry.rules]
    questions = [{"id": q.id, "status": q.status, "applies_to": q.applies_to}
                 for q in registry.undetermined]
    return constraints, questions


def _actions() -> list[dict]:
    from explorer.adapter import SUPPORTED_ACTIONS
    schema = Candidate.model_json_schema()["$defs"]
    out = []
    for name, definition in schema.items():
        action = definition.get("properties", {}).get("action", {})
        if "const" not in action:
            continue
        out.append({
            "action": action["const"],
            "fields": {field: spec for field, spec in definition["properties"].items()
                       if field != "action"},
            "adapter_supported": action["const"] in SUPPORTED_ACTIONS,
            "source": definition.get("description", ""),
        })
    return sorted(out, key=lambda a: a["action"])


def _configspace_summary() -> dict:
    from explorer.config_space import summary  # config_space imports this module
    return summary()


def digest(model: dict) -> str:
    """sha256 over what defines the space: the model without its evidence (smoke run
    IDs), its metadata and the digest itself."""
    semantic = copy.deepcopy({k: v for k, v in model.items()
                              if k not in ("model_digest", "generated_by", "description")})
    for dimension in semantic["dimensions"]:
        for value in dimension["values"]:
            value.pop("smoke_run", None)
    blob = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


@lru_cache(maxsize=1)
def build() -> dict:
    """The model.json content (see the module docstring)."""
    constraints, questions = _constraints()
    rule_ids_by_name: dict[str, list[str]] = {}
    for entry in [*constraints, *questions]:
        for name in entry["applies_to"]:
            rule_ids_by_name.setdefault(name, []).append(entry["id"])
    admitted = {row["name"] for row in admitted_rows()}
    model = {
        "description": ("The explorer's candidate space: P0 schema, admitted dimensions "
                        "with typed values and smoke evidence, P1 constraints by rule ID, "
                        "the action catalog and the pinned versions. Generated by "
                        "scripts/build_model_json.py; don't edit by hand."),
        "generated_by": "scripts/build_model_json.py",
        "schema_version": SCHEMA_VERSION,
        "rules_version": load_rules().version,
        "pinned_versions": pinned_versions(),
        "candidate_schema": Candidate.model_json_schema(),
        "dimensions": _dimensions(rule_ids_by_name),
        "not_admitted": [{"name": row["name"], "kind": row["kind"], "values": row["values"]}
                         for row in _surface_rows()
                         if row["kind"] in ("config", "action") and row["name"] not in admitted],
        "constraints": constraints,
        "open_questions": questions,
        "actions": _actions(),
        "configspace": _configspace_summary(),
    }
    model["model_digest"] = digest(model)
    return model


def render() -> str:
    return json.dumps(build(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write(path: Path = MODEL_JSON) -> Path:
    path.write_text(render(), encoding="utf-8")
    return path
