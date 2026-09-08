"""Regression tests never use the installed database or physical printers."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_data = tempfile.TemporaryDirectory(prefix="tds-tests-")
os.environ["TDS_DATABASE_URL"] = f"sqlite:///{_data.name}/test.db"


@pytest.fixture(autouse=True)
def no_physical_printers():
    with patch("socket.create_connection", side_effect=AssertionError("Tests must mock printer sending")):
        yield
