"""Alembic environment: runs on the connection ``bootstrap.database.migrate`` hands in."""

from alembic import context

if context.is_offline_mode():
    message = "Offline (SQL script) migrations are not supported."
    raise RuntimeError(message)

# SQLite cannot ALTER most things in place; batch mode recreates the table (use
# `op.batch_alter_table` in revisions that change an existing table).
context.configure(
    connection=context.config.attributes["connection"],
    target_metadata=None,
    render_as_batch=True,
    transactional_ddl=True,  # SQLite supports it, and `bootstrap.database` runs every BEGIN
)
with context.begin_transaction():
    context.run_migrations()
