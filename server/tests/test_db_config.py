import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("environment_override", [False, True])
def test_direct_db_import_and_app_use_same_dotenv_url(tmp_path, environment_override):
    """Alembic imports db directly, before main; both must see server/.env."""
    app_dir = tmp_path / "server" / "app"
    app_dir.mkdir(parents=True)
    db_file = app_dir / "db.py"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "app" / "db.py", db_file)
    dotenv_url = f"sqlite:///{tmp_path}/configured.db"
    (app_dir.parent / ".env").write_text(f"TDS_DATABASE_URL={dotenv_url}\n")
    env = {k: v for k, v in os.environ.items() if k != "TDS_DATABASE_URL"}
    expected = f"sqlite:///{tmp_path}/override.db" if environment_override else dotenv_url
    if environment_override:
        env["TDS_DATABASE_URL"] = expected
    result = subprocess.run(
        [sys.executable, "-B", "-c", "import runpy,sys; print(runpy.run_path(sys.argv[1])['engine'].url)", str(db_file)],
        env=env, check=True, capture_output=True, text=True,
    )
    assert result.stdout.strip() == expected
    # Engine construction must not create any database without connecting.
    assert not list(tmp_path.glob("*.db"))
