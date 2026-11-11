"""Smoke-run the values of the dimensions admitted in issue #61 through the candidate
adapter (explorer.adapter.run_candidate), one fresh UML guest each.

Every candidate is the legal F02 configuration (SAE-EXT-KEY on both links, client beacon
protection on, as eht_mld_sae_ext_two_links_client_bp) with one dimension changed, so a
value's run differs from the adapter base run in that dimension only. Each must pass the
modeled rules (validate_candidate -> PASSES_MODELED_RULES); the script refuses otherwise.

    .venv/bin/python scripts/smoke_dimensions.py --check        # validate only, no guest
    .venv/bin/python scripts/smoke_dimensions.py                # run all
    .venv/bin/python scripts/smoke_dimensions.py gcmp_256 base  # run some

Runs land in runs/hwsim-logs/ (git-ignored trials). Move an ACCEPTED run you keep as
evidence to runs/smoke/, describe it in runs/smoke/README.md and point
surface_candidates.csv's smoke_runs at it.
"""

from __future__ import annotations

import argparse
import sys

from explorer.adapter import run_candidate, unsupported
from explorer.model import Candidate
from explorer.scenarios import TEST_CONFIGS
from explorer.validate import validate_candidate

BASE_TEST = "eht_mld_sae_ext_two_links_client_bp"
ASSOC = {"action": "associate"}


def _candidate(actions=(ASSOC,), cipher="CCMP", **ap) -> dict:
    config = TEST_CONFIGS[BASE_TEST].model_dump(mode="json")
    config["ap"].update(ap)
    for link in config["ap"]["links"]:
        link["pairwise_cipher"] = cipher
    return {"config": config, "actions": list(actions)}


# name -> (dimension=value it shows, candidate)
CANDIDATES = {
    "base": ("ap_sae_pwe=unset; ap_pairwise_cipher=CCMP; rekey_gtk_now=absent; "
             "disable_enable_mld=absent", _candidate()),
    "sae_pwe_h2e": ("ap_sae_pwe=1", _candidate(sae_pwe="hash_to_element")),
    "sae_pwe_both": ("ap_sae_pwe=2", _candidate(sae_pwe="both")),
    "gcmp_256": ("ap_pairwise_cipher=GCMP-256", _candidate(cipher="GCMP-256")),
    "rekey_gtk_now": ("rekey_gtk_now=present",
                      _candidate([ASSOC, {"action": "rekey_gtk_now"}])),
    # hostap's order (test_eht.py:727-760): the STA is disconnected while the AP MLD is
    # disabled, so UND.STA_STATE_WHILE_MLD_DISABLED doesn't arise.
    "disable_enable_mld": ("disable_enable_mld=present", _candidate([
        ASSOC,
        {"action": "disable_enable_mld", "command": "DISABLE_MLD"},
        {"action": "sta_disconnect_reconnect", "command": "DISCONNECT"},
        {"action": "disable_enable_mld", "command": "ENABLE_MLD"},
        {"action": "sta_disconnect_reconnect", "command": "RECONNECT"}])),
}


def check(name: str) -> Candidate:
    shows, data = CANDIDATES[name]
    result = validate_candidate(data)
    if result.status != "PASSES_MODELED_RULES":
        sys.exit(f"{name}: {result.status} " + "; ".join(f.rule_id for f in result.findings))
    candidate = Candidate.model_validate(data)
    if reasons := unsupported(candidate):
        sys.exit(f"{name}: the adapter can't run it: " + "; ".join(reasons))
    print(f"{name:20} {result.status:22} P2 {result.p2.status if result.p2 else '-':12} {shows}")
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("names", nargs="*", choices=[[], *CANDIDATES], metavar="NAME",
                        help=f"candidates to run (default: all): {', '.join(CANDIDATES)}")
    parser.add_argument("--check", action="store_true", help="validate only, boot nothing")
    args = parser.parse_args()
    names = args.names or list(CANDIDATES)
    candidates = {name: check(name) for name in names}
    if args.check:
        return
    for name, candidate in candidates.items():
        run = run_candidate(candidate)
        print(f"{name:20} {run.status:10} run {run.run_id} {run.reason or ''}", flush=True)


if __name__ == "__main__":
    main()
