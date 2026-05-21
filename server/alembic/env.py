"""Alembic env — wired to our SQLModel metadata + our app engine.

We don't read ``sqlalchemy.url`` from ``alembic.ini`` because the DB path is
already configured in ``app.db``. SQLite needs ``render_as_batch=True`` to
emulate ``ALTER TABLE`` for column changes.
"""
from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

# Import models so SQLModel.metadata is populated with all our tables.
from app import models  # noqa: F401
from app.db import engine

# Standard alembic config object.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (alembic upgrade --sql)."""
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=engine.url.get_backend_name() == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations using a live connection."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=engine.url.get_backend_name() == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
