"""Alembic environment: runs on the connection ``bootstrap.database.migrate`` hands in."""

from alembic import context

if context.is_offline_mode():
    message = "Offline (SQL script) migrations are not supported."
    raise RuntimeError(message)

connection = context.config.attributes["connection"]
# SQLite cannot ALTER most things in place; batch mode recreates the table (use
# `op.batch_alter_table` in revisions that change an existing table). PostgreSQL alters in place.
context.configure(
    connection=connection,
    target_metadata=None,
    render_as_batch=connection.dialect.name == "sqlite",
    transactional_ddl=True,  # both run DDL in the transaction `bootstrap.database` begins
)
with context.begin_transaction():
    context.run_migrations()
