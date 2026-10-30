import os
import stat
from pathlib import Path

import pytest

from explorer.runner import RunnerError, run_test

BASELINE_RUN = Path(__file__).resolve().parent.parent / "runs" / "baseline" / "1793298094"


def _fake_script(tmp_path: Path, body: str) -> Path:
    """A stand-in for docker/run-test.sh; gets the same env vars and arguments."""
    script = tmp_path / "fake-run-test.sh"
    script.write_text('#!/usr/bin/env bash\nset -eu\nmkdir -p "$LOG_DIR"\n' + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


# --- Outcomes ---------------------------------------------------------------

def test_completed_run_returns_record_and_manifest(tmp_path):
    # Behaves like a passing run-test.sh: copies a run folder into $LOG_DIR.
    script = _fake_script(tmp_path, f"""
cp -R "{BASELINE_RUN}" "$LOG_DIR/1793298094"
echo "PASS $1 0.186547 2026-10-29 18:21:36.508315"
echo "Logs and manifest.json copied to $LOG_DIR/1793298094"
""")
    result = run_test("eht_mld_sae_two_links", log_dir=tmp_path / "logs", script=script)

    assert result.status == "COMPLETED"
    assert result.exit_code == 0
    assert result.run_dir == (tmp_path / "logs" / "1793298094").resolve()
    assert result.record.test_result == "PASS"
    assert result.record.valid_links == "0x3"
    assert result.manifest["run_id"] == "1793298094"


def test_failed_test_is_still_a_completed_run(tmp_path):
    script = _fake_script(tmp_path, f"""
cp -R "{BASELINE_RUN}" "$LOG_DIR/1793298094"
echo "Logs and manifest.json copied to $LOG_DIR/1793298094"
exit 1
""")
    result = run_test("eht_mld_sae_two_links", log_dir=tmp_path / "logs", script=script)

    assert result.status == "COMPLETED"
    assert result.exit_code == 1
    assert result.record is not None


def test_no_run_folder_is_setup_fail(tmp_path):
    script = _fake_script(tmp_path, 'echo "Starting test run in a virtual machine"\nexit 1\n')
    result = run_test("eht_mld_sae_two_links", log_dir=tmp_path / "logs", script=script)

    assert result.status == "SETUP_FAIL"
    assert result.run_dir is None
    assert result.record is None
    assert "Starting test run" in result.output_tail


def test_stuck_run_times_out(tmp_path):
    script = _fake_script(tmp_path, 'echo "Starting test run in a virtual machine"\nsleep 30\n')
    result = run_test("eht_mld_sae_two_links", log_dir=tmp_path / "logs", script=script,
                      timeout_s=1)

    assert result.status == "TIMEOUT"
    assert result.exit_code is None
    assert result.run_dir is None


# --- What the script is given -----------------------------------------------

def test_script_gets_log_dir_image_and_container_name(tmp_path):
    seen = tmp_path / "seen.txt"
    script = _fake_script(tmp_path, f'echo "$1|$LOG_DIR|$IMAGE|$CONTAINER_NAME" > "{seen}"\n')
    run_test("eht_mld_gtk_rekey", log_dir="relative-logs", image="my-image", script=script)

    test, log_dir, image, container = seen.read_text().strip().split("|")
    assert test == "eht_mld_gtk_rekey"
    assert Path(log_dir).is_absolute()
    assert image == "my-image"
    assert container.startswith("wifi7-run-")


# --- Bad input --------------------------------------------------------------

@pytest.mark.parametrize("name", ["", "eht mld", "eht;rm -rf", "../x", "EHT_MLD"])
def test_rejects_non_test_names(tmp_path, name):
    with pytest.raises(ValueError):
        run_test(name, script=_fake_script(tmp_path, "exit 0\n"))


def test_missing_script_is_environment_error(tmp_path):
    with pytest.raises(RunnerError):
        run_test("eht_mld_sae_two_links", script=tmp_path / "nope.sh")


# --- Real environment (opt-in) ----------------------------------------------

@pytest.mark.skipif(os.environ.get("WIFI7_DOCKER_TESTS") != "1",
                    reason="set WIFI7_DOCKER_TESTS=1 to run against the real simulation image")
def test_real_run(tmp_path):
    result = run_test("eht_mld_sae_two_links", log_dir=tmp_path)

    assert result.status == "COMPLETED"
    assert result.record.test_result == "PASS"
    assert result.record.valid_links == "0x3"
