"""The version freeze before the held-out campaign (issue #114)."""

import json

import pytest

from explorer import freeze


def test_current_has_every_frozen_key():
    now = freeze.current()
    assert set(now) == set(freeze.FROZEN_KEYS)
    assert now["model_digest"].startswith("sha256:") and len(now["harness"]) == 64
    assert len(now["hostap_commit"]) == 40 and len(now["rules_sha256"]) == 64


def test_nothing_differs_from_itself():
    now = freeze.current()
    assert freeze.differences(dict(now), now) == []


@pytest.mark.parametrize("key", freeze.FROZEN_KEYS)
def test_a_change_to_any_frozen_key_is_reported(key):
    now = freeze.current()
    frozen = {**now, key: "something else"}
    assert freeze.differences(frozen, now) == [f"{key}: something else -> {now[key]}"]


def test_line_endings_dont_change_the_rules_digest(tmp_path, monkeypatch):
    text = freeze.RULES_YAML.read_bytes().replace(b"\r\n", b"\n")
    crlf = tmp_path / "rules.yaml"
    crlf.write_bytes(text.replace(b"\n", b"\r\n"))
    expected = freeze.current()["rules_sha256"]
    monkeypatch.setattr(freeze, "RULES_YAML", crlf)
    assert freeze.current()["rules_sha256"] == expected


def test_write_records_the_tag_and_the_commit(tmp_path):
    data = freeze.write("test-freeze", tmp_path / "freeze.json")
    on_disk = json.loads((tmp_path / "freeze.json").read_text())
    assert on_disk == data and data["tag"] == "test-freeze" and data["frozen_at"]
    assert freeze.differences(on_disk) == []


@pytest.mark.skipif(not freeze.FREEZE_JSON.exists(), reason="nothing frozen yet (#114)")
def test_the_committed_freeze_still_holds():
    # A rule, model, harness or pin change after the freeze means the held-out campaign
    # isn't held-out any more: rerun it, then refreeze.
    frozen = json.loads(freeze.FREEZE_JSON.read_text())
    assert freeze.differences(frozen) == []
