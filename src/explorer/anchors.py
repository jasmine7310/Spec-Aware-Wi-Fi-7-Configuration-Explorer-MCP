"""Campaign evidence for the four anchor families (issue #77).

``anchor_coverage.csv`` lists each anchor family's three runs of its own hostap test (the
family's reproduction, unchanged here). The campaigns never re-run a family's exact
candidate: they vary the admitted dimensions around the F02 base. So instead this module
adds what the campaigns show for each family, in two generated columns:

- ``campaign_runs``: the committed accepted adapter runs (``contrasts.accepted_runs``:
  ``ACCEPTED``, not negative experiments, passing today's rules, on the pinned commits;
  from ``campaigns/`` and ``contrasts/runs/``) whose candidate has the family's own value
  for every dimension in ``modeled_dimensions``. Those values are read from the family's
  source test (``scenarios.TEST_CANDIDATES``) with ``pruning.current_label``: F02
  SAE-EXT-KEY at both ends, F08 a 5 s PTK rekey, F09 a 5 s GTK rekey, F06 ``link_remove``
  and ``rekey_gtk_now`` both present. The other dimensions vary freely, so these runs
  show the family's behavior across the campaign's settings.
- ``campaign_observed``: for each of the family's behavior facts (``FAMILY_FACTS``), how
  many of those runs gave each value, e.g. ``ptk_rekeys_completed: 1 x8, 0 x17``. Counts
  only, read from the behavior records; no interpretation. Runs under different harnesses
  are counted together, so the facts are ones a harness change doesn't alter
  (``disconnect_reasons``, not ``disconnects``).

``scripts/update_anchor_coverage.py`` rewrites the two columns; ``tests/test_anchor_coverage.py``
fails when they're stale.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any

from explorer.signatures import UNKNOWN

REPO_ROOT = Path(__file__).resolve().parents[2]
ANCHOR_CSV = REPO_ROOT / "anchor_coverage.csv"
GENERATED = ("campaign_runs", "campaign_observed")

# The behavior facts each family is about ("a.b" reads key b of fact a).
FAMILY_FACTS: dict[str, tuple[str, ...]] = {
    "F02": ("association_succeeded", "station_status.key_mgmt",
            "four_way_handshakes_completed"),
    "F08": ("ptk_rekeys_completed", "disconnect_reasons"),
    "F09": ("gtk_rekeys_completed", "data_test_rx_after_last_rekey_ap_links"),
    "F06": ("link_reconfig_valid_links", "gtk_rekeys_completed", "disconnect_reasons"),
}


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def family_labels(row: dict[str, str]) -> dict[str, str]:
    """Dimension -> the family's own model.json label, from its source test."""
    from explorer.pruning import current_label
    from explorer.scenarios import TEST_CANDIDATES
    candidate = TEST_CANDIDATES[row["source_test"]].model_dump(mode="json")
    return {name: current_label(candidate, name) for name in _split(row["modeled_dimensions"])}


def fact_value(facts: dict[str, Any], path: str) -> Any:
    """A fact's value, or a key inside it (``station_status.key_mgmt``); UNKNOWN if absent."""
    name, _, key = path.partition(".")
    value = facts.get(name, UNKNOWN)
    if key:
        value = value.get(key, UNKNOWN) if isinstance(value, dict) else UNKNOWN
    return value


def _label(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))


def evidence(row: dict[str, str], runs: list | None = None) -> dict[str, str]:
    """The two generated columns for one family row."""
    from explorer.contrasts import accepted_runs
    from explorer.pruning import current_label
    runs = accepted_runs() if runs is None else runs
    wanted = family_labels(row)
    matching = sorted((run for candidate, run in runs
                       if all(current_label(candidate, name) == label
                              for name, label in wanted.items())),
                      key=lambda run: run.run_id)
    if not matching:
        return {"campaign_runs": "", "campaign_observed": ""}
    parts = []
    for path in FAMILY_FACTS[row["family_id"]]:
        counts = Counter(_label(fact_value(run.facts, path)) for run in matching)
        values = ", ".join(f"{value} x{n}" for value, n in
                           sorted(counts.items(), key=lambda item: (-item[1], item[0])))
        parts.append(f"{path}: {values}")
    return {"campaign_runs": f"{len(matching)} runs: " + "; ".join(r.run_id for r in matching),
            "campaign_observed": "; ".join(parts)}


def rows(path: Path = ANCHOR_CSV) -> tuple[list[str], list[dict[str, str]]]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames), list(reader)


def render(path: Path = ANCHOR_CSV) -> str:
    """The CSV with the generated columns recomputed (added if missing)."""
    from explorer.contrasts import accepted_runs
    columns, data = rows(path)
    columns = [c for c in columns if c not in GENERATED] + list(GENERATED)
    runs = accepted_runs()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in data:
        writer.writerow({**row, **evidence(row, runs)})
    return buf.getvalue()


def write(path: Path = ANCHOR_CSV) -> None:
    Path(path).write_text(render(path), encoding="utf-8")
