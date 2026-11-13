import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.config import get_settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        # Migrations now run in Render's pre-deploy step while the old version
        # is still serving (T-052), so a migration waiting on a lock held by a
        # live request would queue every later request behind it. Give up on a
        # lock after 5s and on any one statement after 10 minutes instead; the
        # deploy is cancelled and the old version keeps serving. SET LOCAL ends
        # with the transaction, and the whole chain stays in that one
        # transaction. SQLite has neither setting.
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '10min'")
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # A failing statement's error would otherwise print its row values, which
        # can be children's data, into the deploy logs. Only this engine: the app
        # builds its own.
        hide_parameters=True,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
