"""Turn a hostap hwsim run folder into a behavior record of observed facts.

A run folder is what ``docker/run-test.sh`` copies out of the container
(``runs/baseline/<run_id>/`` or ``runs/hwsim-logs/<run_id>/``). Every fact comes
from a specific line or file in that folder; when the evidence isn't there the
fact is ``UNKNOWN``, never guessed. Facts that depend on a test helper logging
something (links, station status, traffic) are ``UNKNOWN`` when that line is absent,
because a test may simply not call the helper. Control-interface events are always
logged when they happen, so their counts are real zeros when the log exists.

Evidence sources, all written by hostap's own test framework:

- ``results.db``: the runner's PASS/FAIL/SKIP for the test.
- ``<test>.log``: control-interface events (``<3>CTRL-EVENT-...``) and lines logged
  by test helpers, e.g. ``_eht_verify_links()`` (``valid_links=``/``active_links=``)
  and ``wpas.get_status()`` (``station status: {...}``).
- ``<test>.hwsim0.pcapng``: the radio capture.
"""

from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

UNKNOWN: Literal["UNKNOWN"] = "UNKNOWN"
Unknown = Literal["UNKNOWN"]

# Station status fields worth keeping; values are hostap's own strings.
STATUS_FIELDS = ("wpa_state", "key_mgmt", "pmf", "sae_group", "sae_h2e",
                 "bigtk_set", "wifi_generation", "ap_mld_addr")

# Matches an event from one interface's own control socket, e.g.
#   "... DEBUG wlan8: <3>CTRL-EVENT-CONNECTED ..."
# but not the duplicated copies on the global socket
#   "... DEBUG wlan8(global): IFNAME=wlan8 <3>..." or "... DEBUG : IFNAME=wlan8 <3>...".
_EVENT = r"DEBUG (?P<ifname>[A-Za-z0-9_]+): <3>"
_CONNECTED = re.compile(_EVENT + r"CTRL-EVENT-CONNECTED .*?ap_mld_addr=(?P<mld>\S+)")
_DISCONNECTED = re.compile(_EVENT + r"CTRL-EVENT-DISCONNECTED .*?reason=(?P<reason>\d+)"
                           r"(?P<local> locally_generated=1)?")
_FOUR_WAY = re.compile(_EVENT + r"EAPOL-4WAY-HS-COMPLETED ")
# Rekey events, as test_eht_mld_ptk_rekey / test_eht_mld_gtk_rekey wait for them at the
# pinned hostap commit. "Key negotiation completed" also fires for the initial
# handshake (just before CTRL-EVENT-CONNECTED), so only those while already
# associated count as PTK rekeys. Only the MLO group-rekey message has been seen
# in real runs; the non-MLO "WPA: Group rekeying completed" is not matched.
_PTK_NEGOTIATED = re.compile(_EVENT + r"WPA: Key negotiation completed ")
_GTK_REKEYED = re.compile(_EVENT + r"MLO RSN: Group rekeying completed ")
_DATA_RX = re.compile(r"DEBUG [A-Za-z0-9]+_link(?P<link>\d+): <3>DATA-TEST-RX ")
_LINKS = re.compile(r"INFO (?P<kind>valid|active)_links=(?P<value>0x[0-9a-fA-F]+)")
_STATUS = re.compile(r"INFO station status: (?P<dict>\{.*\})$")


class Disconnect(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: int
    locally_generated: bool


class BehaviorRecord(BaseModel):
    """Observed facts from one test in one run."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    test: str
    test_result: Literal["PASS", "FAIL", "SKIP"] | Unknown

    association_succeeded: Literal[True] | Unknown
    """A ``CTRL-EVENT-CONNECTED`` event was logged."""

    valid_links: str | Unknown
    """Last ``valid_links=`` bitmap logged by ``_eht_verify_links()``, e.g. ``0x3``."""

    active_links: str | Unknown
    """Last ``active_links=`` bitmap logged by ``_eht_verify_links()``."""

    data_test_rx_ap_links: tuple[int, ...] | Unknown
    """AP link IDs that received ``DATA-TEST-RX`` frames from hostap's traffic test."""

    four_way_handshakes_completed: int | Unknown
    """``EAPOL-4WAY-HS-COMPLETED`` events; ``UNKNOWN`` only if the test log is missing."""

    disconnects: tuple[Disconnect, ...] | Unknown
    """``CTRL-EVENT-DISCONNECTED`` events in order; ``UNKNOWN`` only if the log is missing."""

    station_status: dict[str, str] | Unknown
    """Selected fields (``STATUS_FIELDS``) from the last logged ``station status``."""

    packet_capture_bytes: int | Unknown

    ptk_rekeys_completed: int | Unknown
    """``WPA: Key negotiation completed`` events while already associated."""

    gtk_rekeys_completed: int | Unknown
    """``MLO RSN: Group rekeying completed`` events."""

    data_test_rx_after_last_rekey_ap_links: tuple[int, ...] | Unknown
    """AP links with ``DATA-TEST-RX`` after the last PTK/GTK rekey; ``UNKNOWN`` if none."""

    # Not calibrated yet: no run so far performs these actions, so we don't know
    # which log lines prove them. Fill in once real runs of the matching tests exist.
    ml_probe_handled: Unknown = UNKNOWN
    btm_request_handled: Unknown = UNKNOWN

    def signature(self) -> dict:
        """The facts that define behavior, for comparing runs.

        Leaves out run-specific values (run ID, MAC addresses, capture size) so
        that two runs with the same behavior have equal signatures.
        """
        status = self.station_status
        if status != UNKNOWN:
            status = {k: v for k, v in status.items() if k != "ap_mld_addr"}
        return {
            "test": self.test,
            "test_result": self.test_result,
            "association_succeeded": self.association_succeeded,
            "valid_links": self.valid_links,
            "active_links": self.active_links,
            "data_test_rx_ap_links": self.data_test_rx_ap_links,
            "four_way_handshakes_completed": self.four_way_handshakes_completed,
            "disconnects": (UNKNOWN if self.disconnects == UNKNOWN
                            else [d.model_dump() for d in self.disconnects]),
            "station_status": status,
            "packet_capture_present": (UNKNOWN if self.packet_capture_bytes == UNKNOWN
                                       else self.packet_capture_bytes > 0),
            "ptk_rekeys_completed": self.ptk_rekeys_completed,
            "gtk_rekeys_completed": self.gtk_rekeys_completed,
            "data_test_rx_after_last_rekey_ap_links": self.data_test_rx_after_last_rekey_ap_links,
            "ml_probe_handled": self.ml_probe_handled,
            "btm_request_handled": self.btm_request_handled,
        }


def executed_tests(run_dir: Path) -> list[str]:
    """Tests that actually ran (hostap prefills every test as NOTRUN)."""
    db = run_dir / "results.db"
    if not db.exists():
        return []
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT DISTINCT test FROM results WHERE result != 'NOTRUN' ORDER BY test")
        return [test for (test,) in rows]


def _test_result(run_dir: Path, test: str) -> str:
    db = run_dir / "results.db"
    if not db.exists():
        return UNKNOWN
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        row = conn.execute(
            "SELECT result FROM results WHERE test = ? AND result != 'NOTRUN'",
            (test,)).fetchone()
    if row is None or row[0] not in ("PASS", "FAIL", "SKIP"):
        return UNKNOWN
    return row[0]


def extract_record(run_dir: Path | str, test: str | None = None) -> BehaviorRecord:
    """Build the behavior record for ``test`` in ``run_dir``.

    ``test`` may be omitted when the run contains exactly one test.
    """
    run_dir = Path(run_dir)
    if test is None:
        tests = executed_tests(run_dir)
        if len(tests) != 1:
            raise ValueError(f"{run_dir}: expected one test in results.db, found {tests}; "
                             "pass test= explicitly")
        test = tests[0]

    log = run_dir / f"{test}.log"
    lines = log.read_text(errors="replace").splitlines() if log.exists() else []

    connected = False
    associated = False  # between CTRL-EVENT-CONNECTED and CTRL-EVENT-DISCONNECTED
    links: dict[str, str] = {}
    rx_links: set[int] = set()
    rx_links_since_rekey: set[int] = set()
    four_way = 0
    ptk_rekeys = 0
    gtk_rekeys = 0
    disconnects: list[Disconnect] = []
    status: dict[str, str] | None = None

    for line in lines:
        if _CONNECTED.search(line):
            connected = associated = True
        elif m := _DISCONNECTED.search(line):
            associated = False
            disconnects.append(Disconnect(reason=int(m["reason"]),
                                          locally_generated=m["local"] is not None))
        elif _FOUR_WAY.search(line):
            four_way += 1
        elif _PTK_NEGOTIATED.search(line):
            if associated:
                ptk_rekeys += 1
                rx_links_since_rekey = set()
        elif _GTK_REKEYED.search(line):
            gtk_rekeys += 1
            rx_links_since_rekey = set()
        elif m := _DATA_RX.search(line):
            rx_links.add(int(m["link"]))
            rx_links_since_rekey.add(int(m["link"]))
        elif m := _LINKS.search(line):
            links[m["kind"]] = m["value"].lower()
        elif m := _STATUS.search(line):
            parsed = ast.literal_eval(m["dict"])
            status = {k: parsed[k] for k in STATUS_FIELDS if k in parsed}

    pcap = run_dir / f"{test}.hwsim0.pcapng"
    have_log = log.exists()

    return BehaviorRecord(
        run_id=run_dir.name,
        test=test,
        test_result=_test_result(run_dir, test),
        association_succeeded=True if connected else UNKNOWN,
        valid_links=links.get("valid", UNKNOWN),
        active_links=links.get("active", UNKNOWN),
        data_test_rx_ap_links=tuple(sorted(rx_links)) if rx_links else UNKNOWN,
        four_way_handshakes_completed=four_way if have_log else UNKNOWN,
        disconnects=tuple(disconnects) if have_log else UNKNOWN,
        station_status=status if status is not None else UNKNOWN,
        packet_capture_bytes=pcap.stat().st_size if pcap.exists() else UNKNOWN,
        ptk_rekeys_completed=ptk_rekeys if have_log else UNKNOWN,
        gtk_rekeys_completed=gtk_rekeys if have_log else UNKNOWN,
        data_test_rx_after_last_rekey_ap_links=(
            tuple(sorted(rx_links_since_rekey)) if ptk_rekeys or gtk_rekeys else UNKNOWN),
    )
