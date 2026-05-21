from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "tds.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(engine, "connect")
def _sqlite_on_connect(dbapi_connection, _conn_record) -> None:
    """Apply per-connection SQLite tuning.

    * **WAL** mode keeps writers in ``tds.db-wal``; the main file rarely
      changes, so ``uvicorn --reload`` won't restart on every INSERT.
    * **foreign_keys=ON** so our FK constraints are actually enforced
      (SQLite ignores them by default).
    * **busy_timeout** gives concurrent transactions a 5 s grace period
      instead of immediately raising "database is locked".
    """
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def get_session():
    with Session(engine) as session:
        yield session
