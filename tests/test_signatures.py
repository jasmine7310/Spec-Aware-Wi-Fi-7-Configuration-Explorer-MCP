import sqlite3
from pathlib import Path

import pytest

from explorer.signatures import UNKNOWN, Disconnect, extract_record, executed_tests

BASELINE = Path(__file__).resolve().parent.parent / "runs" / "baseline"
BASELINE_RUNS = ["1793298094", "1793298125", "1793298146"]


# --- Real baseline runs -------------------------------------------------------
# Expected values were read from these runs' logs and results.db.

@pytest.mark.parametrize("run_id", BASELINE_RUNS)
def test_baseline_record(run_id):
    record = extract_record(BASELINE / run_id)

    assert record.run_id == run_id
    assert record.test == "eht_mld_sae_two_links"
    assert record.test_result == "PASS"
    assert record.association_succeeded is True
    assert record.valid_links == "0x3"
    assert record.active_links == "0x3"
    assert record.data_test_rx_ap_links == (0, 1)
    assert record.four_way_handshakes_completed == 1
    assert record.disconnects == (Disconnect(reason=3, locally_generated=True),)
    assert record.station_status == {
        "wpa_state": "COMPLETED",
        "key_mgmt": "SAE",
        "pmf": "2",
        "sae_group": "19",
        "sae_h2e": "1",
        "bigtk_set": "1",
        "wifi_generation": "7",
        "ap_mld_addr": "02:00:00:00:07:00",
    }
    assert record.packet_capture_bytes > 0


def test_baseline_signatures_match():
    signatures = [extract_record(BASELINE / run_id).signature() for run_id in BASELINE_RUNS]
    assert signatures[0] == signatures[1] == signatures[2]


def test_signature_omits_run_specific_values():
    signature = extract_record(BASELINE / BASELINE_RUNS[0]).signature()
    assert "run_id" not in signature
    assert "ap_mld_addr" not in signature["station_status"]
    assert signature["packet_capture_present"] is True


def test_uncalibrated_facts_stay_unknown():
    record = extract_record(BASELINE / BASELINE_RUNS[0])
    assert record.ptk_rekey_completed == UNKNOWN
    assert record.gtk_rekey_completed == UNKNOWN
    assert record.ml_probe_handled == UNKNOWN
    assert record.btm_request_handled == UNKNOWN


# --- Missing evidence ---------------------------------------------------------

def _results_db(run_dir: Path, rows):
    with sqlite3.connect(run_dir / "results.db") as conn:
        conn.execute("CREATE TABLE results (test,result,run,time,duration,build,commitid)")
        conn.executemany("INSERT INTO results (test, result) VALUES (?, ?)", rows)


def test_empty_run_folder_is_all_unknown(tmp_path):
    record = extract_record(tmp_path, test="eht_mld_sae_two_links")

    assert record.test_result == UNKNOWN
    assert record.association_succeeded == UNKNOWN
    assert record.valid_links == UNKNOWN
    assert record.active_links == UNKNOWN
    assert record.data_test_rx_ap_links == UNKNOWN
    assert record.four_way_handshakes_completed == UNKNOWN
    assert record.disconnects == UNKNOWN
    assert record.station_status == UNKNOWN
    assert record.packet_capture_bytes == UNKNOWN
    assert record.signature()["packet_capture_present"] == UNKNOWN


def test_log_without_events_reports_zero_not_unknown(tmp_path):
    # The log exists, so "no handshakes/disconnects seen" is a real observation.
    (tmp_path / "some_test.log").write_text("2026-10-29 18:21:36,321 INFO START some_test 1/1\n")
    record = extract_record(tmp_path, test="some_test")

    assert record.four_way_handshakes_completed == 0
    assert record.disconnects == ()
    assert record.association_succeeded == UNKNOWN


def test_global_socket_duplicates_are_not_double_counted(tmp_path):
    # Lines copied from a baseline log: the same event on the interface socket
    # and on the global control socket.
    (tmp_path / "t.log").write_text(
        "2026-10-29 18:21:36,507 DEBUG wlan8: <3>CTRL-EVENT-DISCONNECTED "
        "bssid=02:00:00:00:07:00 reason=3 locally_generated=1\n"
        "2026-10-29 18:21:36,507 DEBUG : IFNAME=wlan8 <3>CTRL-EVENT-DISCONNECTED "
        "bssid=02:00:00:00:07:00 reason=3 locally_generated=1\n"
        "2026-10-29 18:21:36,506 DEBUG wlan8(global): IFNAME=wlan8 <3>CTRL-EVENT-DISCONNECTED "
        "bssid=02:00:00:00:07:00 reason=3 locally_generated=1\n")
    record = extract_record(tmp_path, test="t")
    assert record.disconnects == (Disconnect(reason=3, locally_generated=True),)


# --- Picking the test ---------------------------------------------------------

def test_executed_tests_ignores_notrun(tmp_path):
    _results_db(tmp_path, [("a", "NOTRUN"), ("b", "PASS"), ("b", "NOTRUN")])
    assert executed_tests(tmp_path) == ["b"]


def test_ambiguous_run_needs_explicit_test(tmp_path):
    _results_db(tmp_path, [("a", "PASS"), ("b", "FAIL")])
    with pytest.raises(ValueError):
        extract_record(tmp_path)
    assert extract_record(tmp_path, test="b").test_result == "FAIL"
