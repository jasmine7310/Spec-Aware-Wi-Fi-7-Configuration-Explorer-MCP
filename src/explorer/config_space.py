"""The static settings as a ConfigSpace space (issue #63), with each condition and
forbidden clause tagged with the ``rules.yaml`` rule it encodes.

Hyperparameters are the admitted dimensions that are settings (``model.json``; actions
stay out, as the roadmap suggests: their order is ``validate.check_action_order``'s job),
plus the two beacon-protection settings. Those aren't dimensions (one legal value each),
but carrying them lets ConfigSpace express ``SEC.EHT_BEACON_PROT`` as a forbidden value.
Values are ``model.json``'s labels; an inactive hyperparameter means the setting is unset.

What ConfigSpace encodes (``CONSTRAINTS``):

- ``SEC.SAE_PWE_NEEDS_SAE``: conditions. ``ap_sae_pwe`` / ``sta_sae_pwe`` are active only
  when that side's AKM is SAE-family; setting one while inactive is invalid.
- ``SEC.MLD_CLIENT_COMMON_AKM``: forbidden conjunctions of an AP AKM with a different
  client AKM. In this space each side has one AKM, shared by every link, so a common AKM
  means the same AKM.
- ``SEC.SAE_H2E_ONLY_NEEDS_STA_H2E``: forbidden ``ap_sae_pwe=1`` with ``sta_sae_pwe=unset``
  (both active, so both sides use an SAE AKM and every link offers only it).
- ``SEC.EHT_BEACON_PROT``: forbidden ``0`` on either side.

What stays a P1 predicate (``PREDICATE_ONLY``, with the reason), because ConfigSpace's
categorical hyperparameters can't express it or because no value in this space reaches
it: per-link AKM lists and their intersection (``SEC.MLD_COMMON_SUITES``), plain SAE
(``SEC.EHT_SAE_AKM``, ``SEC.EHT_SAE_H2E``: not an admitted value), PMF off (``SEC.PMF``:
P0 has no such value), the link layout (P0: at most two links on different channels), the
action-order rules and the open questions. ``tests/test_config_space.py`` checks that
ConfigSpace and the P1 predicates agree on every combination of these hyperparameters, so
the two can't drift apart.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from functools import lru_cache

import ConfigSpace as CS

from explorer import model_json

SAE_FAMILY = ("SAE", "SAE-EXT-KEY")
UNSET = "unset"
# Fixed settings carried only so a rule can forbid their other value.
FIXED_SETTINGS = {"ap_beacon_protection": ("1", "0"), "sta_beacon_protection": ("1", "0")}


@dataclass(frozen=True)
class Constraint:
    """One condition or forbidden clause, as ConfigSpace gets it and as we explain it."""
    rule_id: str
    kind: str                       # "condition" or "forbidden"
    # condition: child is active only when parent's value is in values
    # forbidden: every (hyperparameter, value) in clauses holds at once
    child: str | None = None
    parent: str | None = None
    values: tuple[str, ...] = ()
    clauses: tuple[tuple[str, str], ...] = ()

    def violated_by(self, values: dict[str, str]) -> bool:
        """Whether this constraint rejects ``values`` (hyperparameter -> label; an
        inactive or unset setting may be absent or "unset")."""
        if self.kind == "condition":
            active = values.get(self.parent) in self.values
            return not active and values.get(self.child, UNSET) != UNSET
        return all(values.get(name) == value for name, value in self.clauses)

    def describe(self) -> str:
        if self.kind == "condition":
            return f"{self.child} only when {self.parent} in {list(self.values)}"
        return " and ".join(f"{name}={value}" for name, value in self.clauses) + " is forbidden"


# rule_id -> why ConfigSpace doesn't carry it; P1 (or P0) checks it instead.
PREDICATE_ONLY = {
    "SEC.MLD_COMMON_SUITES": (
        "per-link AKM lists and pairwise ciphers, compared by intersection; categorical "
        "hyperparameters can't express list intersection. In this space every link gets the "
        "same AKM and cipher (model_json.apply), so it can't fire here; P1 checks it"),
    "SEC.EHT_SAE_AKM": "plain SAE (AKM 8) isn't an admitted value; P1 checks other candidates",
    "SEC.EHT_SAE_H2E": "fires only with plain SAE, which isn't an admitted value; P1 checks it",
    "SEC.PMF": "PMF off isn't a value P0 accepts; nothing for ConfigSpace to forbid",
    "AO.*": "action order: actions stay out of ConfigSpace; validate.check_action_order",
    "UND.*": "open questions (SPEC_UNDETERMINED): validate.find_undetermined",
    "P0 link layout": "at most two links on different channels: model.ApConfig's validators",
}


def _dimensions() -> dict[str, list[str]]:
    """The admitted setting dimensions (not actions) with their labels, in model.json
    order. Read from the same source model.json is built from (not from model.json, which
    records this module's summary)."""
    return {row["name"]: list(model_json._smoke_runs(row))
            for row in model_json.admitted_rows()
            if model_json.DIMENSIONS[row["name"]][0] != "actions"}


@lru_cache(maxsize=1)
def hyperparameter_values() -> dict[str, tuple[str, ...]]:
    """Every hyperparameter and its labels: the setting dimensions, then FIXED_SETTINGS.
    For a conditional one, ``unset`` stays a value: SAE with sae_pwe unset is legal."""
    out = {name: tuple(labels) for name, labels in _dimensions().items()}
    out.update(FIXED_SETTINGS)
    return out


@lru_cache(maxsize=1)
def constraints() -> tuple[Constraint, ...]:
    hps = hyperparameter_values()
    akms = sorted(set(hps["ap_akm"]) | set(hps["sta_akm"]))
    sae = tuple(a for a in akms if a in SAE_FAMILY)
    out = [
        Constraint("SEC.SAE_PWE_NEEDS_SAE", "condition", child="ap_sae_pwe", parent="ap_akm",
                   values=sae),
        Constraint("SEC.SAE_PWE_NEEDS_SAE", "condition", child="sta_sae_pwe", parent="sta_akm",
                   values=sae),
    ]
    out += [Constraint("SEC.MLD_CLIENT_COMMON_AKM", "forbidden",
                       clauses=(("ap_akm", ap), ("sta_akm", sta)))
            for ap, sta in itertools.product(hps["ap_akm"], hps["sta_akm"]) if ap != sta]
    out.append(Constraint("SEC.SAE_H2E_ONLY_NEEDS_STA_H2E", "forbidden",
                          clauses=(("ap_sae_pwe", "1"), ("sta_sae_pwe", UNSET))))
    out += [Constraint("SEC.EHT_BEACON_PROT", "forbidden", clauses=((name, "0"),))
            for name in FIXED_SETTINGS]
    return tuple(out)


@lru_cache(maxsize=1)
def space() -> CS.ConfigurationSpace:
    """The ConfigSpace space: one Categorical per hyperparameter, the conditions and the
    forbidden clauses (each tagged with its rule ID in ``constraints()``)."""
    hps = hyperparameter_values()
    cs = CS.ConfigurationSpace(name="wifi7-explorer static settings", seed=0)
    params = {name: CS.Categorical(name, list(values), default=values[0])
              for name, values in hps.items()}
    cs.add(list(params.values()))
    for c in constraints():
        if c.kind == "condition":
            cs.add(CS.InCondition(params[c.child], params[c.parent], list(c.values)))
        elif len(c.clauses) == 1:
            (name, value), = c.clauses
            cs.add(CS.ForbiddenEqualsClause(params[name], value))
        else:
            cs.add(CS.ForbiddenAndConjunction(
                *(CS.ForbiddenEqualsClause(params[name], value) for name, value in c.clauses)))
    return cs


def _active_values(values: dict[str, str]) -> dict[str, str]:
    """``values`` in ConfigSpace's terms: a conditional hyperparameter whose condition
    doesn't hold is left out when it's unset (inactive), kept otherwise (then invalid)."""
    out = dict(values)
    for c in constraints():
        if c.kind == "condition" and out.get(c.parent) not in c.values \
                and out.get(c.child, UNSET) == UNSET:
            out.pop(c.child, None)
    return out


def is_valid(values: dict[str, str]) -> bool:
    """ConfigSpace's own verdict on a full assignment of every hyperparameter."""
    try:
        CS.Configuration(space(), values=_active_values(values)).check_valid_configuration()
    except (ValueError, CS.ForbiddenValueError):   # inactive set, active unset, forbidden
        return False
    return True


def violations(values: dict[str, str]) -> list[str]:
    """Rule IDs of the constraints ``values`` breaks, for explaining a rejection. Read like
    ConfigSpace reads them: a forbidden clause never fires on an inactive hyperparameter
    (e.g. the client's sae_pwe when the client allows no SAE AKM)."""
    inactive = {c.child for c in constraints()
                if c.kind == "condition" and values.get(c.parent) not in c.values}
    active = {name: value for name, value in values.items() if name not in inactive}
    return sorted({c.rule_id for c in constraints()
                   if c.violated_by(values if c.kind == "condition" else active)})


def candidate(values: dict[str, str]) -> dict:
    """The candidate (JSON) these hyperparameter values describe: model_json.apply for
    the dimensions on the F02 base (associate only), then the fixed settings."""
    data = model_json.apply({name: label for name, label in values.items()
                             if name not in FIXED_SETTINGS})
    data["config"]["ap"]["beacon_protection"] = values.get("ap_beacon_protection", "1") == "1"
    data["config"]["sta"]["beacon_protection"] = values.get("sta_beacon_protection", "1") == "1"
    return data


def summary() -> dict:
    """What model.json records about the ConfigSpace encoding."""
    return {
        "status": "built (explorer.config_space)",
        "hyperparameters": {name: list(values) for name, values in hyperparameter_values().items()},
        "constraints": [{"rule_id": c.rule_id, "kind": c.kind, "encodes": c.describe()}
                        for c in constraints()],
        "predicate_only": PREDICATE_ONLY,
        "agreement": "tests/test_config_space.py: ConfigSpace and the P1 predicates agree on "
                     "every combination of these hyperparameters, verdict and rule IDs",
    }
