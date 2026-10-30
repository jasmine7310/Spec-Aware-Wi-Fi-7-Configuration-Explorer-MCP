"""Run hostap hwsim tests in the simulation environment from Python (P3).

``run_test()`` calls ``docker/run-test.sh`` for one test, which boots a fresh UML
guest in a fresh container, and turns what comes back into a ``RunResult``:

- ``COMPLETED``: the test ran and its run folder came back. Whether hostap's test
  passed is in ``record.test_result``; a FAIL here is still a completed run.
- ``SETUP_FAIL``: no run folder came back (e.g. the guest didn't boot or the
  container couldn't start the test).
- ``TIMEOUT``: the run took longer than ``timeout_s``; its container is removed.

Problems with the environment itself (no Docker, Docker not running, missing
image) raise ``RunnerError`` instead, since they say nothing about the candidate.

How these map onto the spec's P3 outcomes (ACCEPTED / REJECTED / SETUP_FAIL /
TIMEOUT) is left to the candidate-to-test layer, which knows what each test was
expected to show.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from explorer.signatures import BehaviorRecord, extract_record

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SCRIPT = REPO_ROOT / "docker" / "run-test.sh"
DEFAULT_LOG_DIR = REPO_ROOT / "runs" / "hwsim-logs"
DEFAULT_IMAGE = "wifi7-env"
DEFAULT_TIMEOUT_S = 600

RunStatus = Literal["COMPLETED", "SETUP_FAIL", "TIMEOUT"]

# hwsim test names as used by run-tests.py, e.g. "eht_mld_sae_two_links".
_TEST_NAME = re.compile(r"^[a-z0-9_]+$")
# Printed by run-test.sh once the run folder is on the host.
_COPIED = re.compile(r"^Logs and manifest\.json copied to (?P<dir>.+)$", re.MULTILINE)
_OUTPUT_TAIL_LINES = 40


class RunnerError(RuntimeError):
    """The simulation environment can't run tests at all."""


class RunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    test: str
    status: RunStatus
    run_dir: Path | None
    """Host folder with the run's logs; ``None`` unless ``COMPLETED``."""
    record: BehaviorRecord | None
    manifest: dict | None
    exit_code: int | None
    """``run-test.sh`` exit code (0 only if the test passed); ``None`` on timeout."""
    output_tail: str
    """Last lines of the run's console output, for debugging."""


def check_environment(image: str = DEFAULT_IMAGE) -> None:
    """Raise ``RunnerError`` unless Docker is running and ``image`` exists."""
    try:
        info = subprocess.run(["docker", "info", "-f", "{{.Architecture}}"],
                              capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise RunnerError("docker not found; install Docker Desktop") from None
    if info.returncode != 0:
        raise RunnerError("Docker isn't running; start Docker Desktop")
    if info.stdout.strip() not in ("x86_64", "amd64"):
        raise RunnerError(f"Docker runs on {info.stdout.strip()}; UML needs x86-64")
    image_check = subprocess.run(["docker", "image", "inspect", image],
                                 capture_output=True, text=True, timeout=30)
    if image_check.returncode != 0:
        raise RunnerError(f"image {image!r} not found; build it with scripts/build-env.sh")


def run_test(test: str, *,
             log_dir: Path | str = DEFAULT_LOG_DIR,
             image: str = DEFAULT_IMAGE,
             timeout_s: float = DEFAULT_TIMEOUT_S,
             script: Path | str = RUN_SCRIPT) -> RunResult:
    """Run one hwsim test in a fresh guest and return what was observed.

    ``log_dir`` defaults to the git-ignored trial folder; pass ``runs/baseline``
    (or similar) for runs that should be kept as evidence. ``script`` exists so
    tests can substitute a fake; with the real script, the environment is
    checked first.
    """
    if not _TEST_NAME.match(test):
        raise ValueError(f"not a hwsim test name: {test!r}")
    script = Path(script)
    if not script.exists():
        raise RunnerError(f"run script not found: {script}")
    if script.resolve() == RUN_SCRIPT.resolve():
        check_environment(image)

    log_dir = Path(log_dir).resolve()
    container = f"wifi7-run-{uuid.uuid4().hex[:12]}"
    env = {**os.environ, "LOG_DIR": str(log_dir), "IMAGE": image,
           "CONTAINER_NAME": container}

    # Own process group, so a timeout can stop the script and everything it started.
    proc = subprocess.Popen([str(script), test], env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        output, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        output, _ = proc.communicate()
        try:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return RunResult(test=test, status="TIMEOUT", run_dir=None, record=None,
                         manifest=None, exit_code=None, output_tail=_tail(output))

    match = _COPIED.search(output)
    if match is None:
        return RunResult(test=test, status="SETUP_FAIL", run_dir=None, record=None,
                         manifest=None, exit_code=proc.returncode,
                         output_tail=_tail(output))

    run_dir = Path(match["dir"].strip()).resolve()
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    return RunResult(test=test, status="COMPLETED", run_dir=run_dir,
                     record=extract_record(run_dir, test), manifest=manifest,
                     exit_code=proc.returncode, output_tail=_tail(output))


def _tail(output: str | None) -> str:
    lines = (output or "").splitlines()
    return "\n".join(lines[-_OUTPUT_TAIL_LINES:])
