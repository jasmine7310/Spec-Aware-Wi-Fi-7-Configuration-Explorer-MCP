import importlib

import pytest

MODULES = [
    "explorer",
    "explorer.model",
    "explorer.rules",
    "explorer.validate",
    "explorer.planner",
    "explorer.runner",
    "explorer.cache",
    "explorer.signatures",
    "explorer.minimize",
    "explorer.mcp_server",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)
