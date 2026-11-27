"""The version freeze before the held-out campaign (issue #114)."""

import ast
import json

import pytest

from explorer import freeze


def test_current_has_every_frozen_key():
    now = freeze.current()
    assert set(now) == set(freeze.FROZEN_KEYS)
    assert now["model_digest"].startswith("sha256:") and len(now["harness"]) == 64
    assert len(now["hostap_commit"]) == 40 and len(now["rules_sha256"]) == 64
    assert len(now["code_sha256"]) == 64


def _explorer_imports(name):
    """The explorer modules a module imports, anywhere in it (also inside functions)."""
    tree = ast.parse((freeze.REPO_ROOT / "src" / "explorer" / f"{name}.py").read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "explorer":
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("explorer."):
            found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            found |= {a.name.split(".")[1] for a in node.names
                      if a.name.startswith("explorer.")}
    return found


def test_pipeline_modules_are_closed_under_imports():
    # Everything planner and campaign import, directly or not, is frozen: a module the
    # pipeline starts importing must join PIPELINE_MODULES.
    closure, todo = set(), ["planner", "campaign"]
    while todo:
        name = todo.pop()
        if name not in closure:
            closure.add(name)
            todo.extend(_explorer_imports(name))
    assert closure <= set(freeze.PIPELINE_MODULES), closure - set(freeze.PIPELINE_MODULES)
    assert all((freeze.REPO_ROOT / f).is_file() for f in freeze.CODE_FILES)


def test_code_digest_sees_a_change_but_not_line_endings(tmp_path):
    files = ("src/explorer/validate.py", "scripts/run_campaign.py")
    for f in files:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_bytes((freeze.REPO_ROOT / f).read_bytes().replace(b"\r\n", b"\n"))
    before = freeze.code_digest(files, tmp_path)
    assert before == freeze.code_digest(files, freeze.REPO_ROOT)
    validate = tmp_path / files[0]
    validate.write_bytes(validate.read_bytes().replace(b"\n", b"\r\n"))
    assert freeze.code_digest(files, tmp_path) == before
    validate.write_bytes(validate.read_bytes() + b"# a change\n")
    assert freeze.code_digest(files, tmp_path) != before


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
