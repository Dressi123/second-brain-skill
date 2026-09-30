"""Point every test at a throwaway vault, never the real one.

This has to happen before anything imports vault_tools or the helpers:
vault_paths reads $SECOND_BRAIN_VAULT once, at import time, and on the
author's Mac the fallback is the live iCloud vault.
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VAULT = Path(tempfile.mkdtemp(prefix="second-brain-test-vault-"))
atexit.register(shutil.rmtree, VAULT, ignore_errors=True)

os.environ["SECOND_BRAIN_VAULT"] = str(VAULT)
os.environ["SECOND_BRAIN_HELPERS"] = str(REPO / "helpers")
sys.path.insert(0, str(REPO / "mcp-server"))

import vault_tools as vt  # noqa: E402

# A machine with a local vault clone would git-pull before every read and
# push after every write. Tests must do neither.
vt.GIT_DIR = Path("/nonexistent")

HUB = """\
---
title: "Test Project"
type: project
id: test-project
tags: [project-hub, project/test-project]
created: 2026-01-01
---

# Test Project

A project hub for the test suite.
"""

NOTE = """\
---
date: 2026-01-02
tags: [project/test-project]
description: How the widget flux capacitor was fixed
---

# Widget fix

The flux capacitor needed a new gasket.
"""


@pytest.fixture(autouse=True)
def vault():
    """A fresh, small vault for every test."""
    for p in sorted(VAULT.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    (VAULT / "Projects").mkdir()
    (VAULT / "Projects" / "Test Project.md").write_text(HUB)
    (VAULT / "Notes" / "Topics").mkdir(parents=True)
    (VAULT / "Notes" / "Widget fix.md").write_text(NOTE)
    (VAULT / "Claude Archive" / "Bulk export").mkdir(parents=True)
    (VAULT / "Claude Archive" / "Bulk export" / "old.md").write_text("# Old\n")
    return VAULT


@pytest.fixture
def anyio_backend():
    return "asyncio"
