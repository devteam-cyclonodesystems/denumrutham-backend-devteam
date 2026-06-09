from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context
from alembic.operations import Operations
from alembic.operations import BatchOperations
from sqlalchemy.exc import NoSuchTableError
import uuid
import sqlite3
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

# Register UUID adapter for SQLite compatibility
sqlite3.register_adapter(uuid.UUID, str)

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"

# Save original Operations methods
for method_name in ['create_table', 'drop_table', 'add_column', 'alter_column', 'drop_column', 'create_index', 'drop_index', 'create_foreign_key', 'drop_constraint', 'create_unique_constraint', 'execute']:
    setattr(Operations, f"_orig_{method_name}", getattr(Operations, method_name))

def sqlite_friendly_wrapper(func_name):
    def wrapper(self, *args, **kwargs):
        dialect = self.get_bind().dialect.name
        try:
            if dialect == 'sqlite':
                # Translate to batch operations where SQLite does not support direct DDL
                if func_name == 'alter_column':
                    table_name, column_name = args[0], args[1]
                    remaining_args = args[2:]
                    with self.batch_alter_table(table_name) as batch_op:
                        return batch_op.alter_column(column_name, *remaining_args, **kwargs)
                elif func_name == 'drop_column':
                    table_name, column_name = args[0], args[1]
                    with self.batch_alter_table(table_name) as batch_op:
                        return batch_op.drop_column(column_name, **kwargs)
                elif func_name == 'add_column':
                    table_name, column = args[0], args[1]
                    with self.batch_alter_table(table_name) as batch_op:
                        return batch_op.add_column(column, **kwargs)
                elif func_name == 'create_foreign_key':
                    name, source_table, referent_table, local_cols, remote_cols = args[0], args[1], args[2], args[3], args[4]
                    if not name:
                        name = f"fk_{source_table}_{'_'.join(local_cols)}"
                    with self.batch_alter_table(source_table) as batch_op:
                        return batch_op.create_foreign_key(name, referent_table, local_cols, remote_cols, **kwargs)
                elif func_name == 'drop_constraint':
                    name, table_name = args[0], args[1]
                    with self.batch_alter_table(table_name) as batch_op:
                        return batch_op.drop_constraint(name, **kwargs)
                elif func_name == 'create_unique_constraint':
                    name, table_name, columns = args[0], args[1], args[2]
                    if not name:
                        name = f"uq_{table_name}_{'_'.join(columns)}"
                    with self.batch_alter_table(table_name) as batch_op:
                        return batch_op.create_unique_constraint(name, columns, **kwargs)
            
            orig_func = getattr(Operations, f"_orig_{func_name}")
            return orig_func(self, *args, **kwargs)
        except (NoSuchTableError, KeyError) as e:
            if dialect == 'sqlite':
                return None
            raise
        except Exception as e:
            if dialect == 'sqlite':
                err_msg = str(e).lower()
                ignores = [
                    "already exists",
                    "duplicate column name",
                    "duplicate",
                    "no such table",
                    "no such column",
                    "no such index",
                    "no such constraint",
                    "no such",
                    "keyerror",
                    "near \"enable\"",
                    "near \"policy\"",
                    "near \"constraint\"",
                    "near \"(\"",
                    "near \"alter\"",
                    "near \"do\"",
                    "near \"index\"",
                    "constraint must have a name"
                ]
                if any(ign in err_msg for ign in ignores):
                    return None
            raise
    return wrapper

# Wrap Operations methods
for method_name in ['create_table', 'drop_table', 'add_column', 'alter_column', 'drop_column', 'create_index', 'drop_index', 'create_foreign_key', 'drop_constraint', 'create_unique_constraint', 'execute']:
    setattr(Operations, method_name, sqlite_friendly_wrapper(method_name))

# Decorate BatchOperations methods with error bypass
def ignore_errors_sqlite(func):
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except (NoSuchTableError, KeyError) as e:
            if self.get_bind().dialect.name == 'sqlite':
                return None
            raise
        except Exception as e:
            if self.get_bind().dialect.name == 'sqlite':
                err_msg = str(e).lower()
                ignores = [
                    "already exists",
                    "duplicate column name",
                    "duplicate",
                    "no such table",
                    "no such column",
                    "no such index",
                    "no such constraint",
                    "no such",
                    "keyerror",
                    "near \"enable\"",
                    "near \"policy\"",
                    "near \"constraint\"",
                    "near \"(\"",
                    "near \"alter\"",
                    "near \"do\"",
                    "near \"index\"",
                    "constraint must have a name"
                ]
                if any(ign in err_msg for ign in ignores):
                    return None
            raise
    return wrapper

for method_name in ['add_column', 'alter_column', 'drop_column', 'create_foreign_key', 'drop_constraint', 'create_unique_constraint']:
    orig_batch_func = getattr(BatchOperations, method_name)
    setattr(BatchOperations, method_name, ignore_errors_sqlite(orig_batch_func))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from app.db.base import Base
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    from app.core.config import settings
    from sqlalchemy import create_engine
    
    db_url = str(settings.DATABASE_URL).replace("+asyncpg", "").replace("+aiosqlite", "")
    connectable = create_engine(db_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
