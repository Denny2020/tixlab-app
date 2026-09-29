from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.config import settings
from app.db import Base, normalize_url

target_metadata = Base.metadata
url = normalize_url(settings.database_url)

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url, poolclass=pool.NullPool).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
