from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from fastapi import Request
import urllib.parse
from app.core.config import settings

# Parse and sanitize DATABASE_URL for asyncpg (which does not support sslmode directly)
db_url = settings.DATABASE_URL
connect_args = {}

if db_url.startswith("postgresql+asyncpg"):
    parsed = urllib.parse.urlparse(db_url)
    query_params = urllib.parse.parse_qs(parsed.query)
    if "sslmode" in query_params:
        sslmode = query_params["sslmode"][0]
        del query_params["sslmode"]
        if sslmode in ("require", "prefer", "allow"):
            connect_args["ssl"] = True
    new_query = urllib.parse.urlencode(query_params, doseq=True)
    parsed = parsed._replace(query=new_query)
    db_url = urllib.parse.urlunparse(parsed)

engine = create_async_engine(
    db_url,
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args=connect_args,
)


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models (SQLAlchemy 2.0 style)."""
    pass

async def get_db(request: Request = None) -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing a database session with RLS context."""
    async with AsyncSessionLocal() as session:
        # Set RLS context if request is available (Defense-in-Depth #5)
        if engine.dialect.name != "sqlite":
            if request:
                temple_id = getattr(request.state, "temple_id", None)
                user_role = getattr(request.state, "user_role", "GUEST")
                
                # Set session variables for RLS policies
                if temple_id:
                    await session.execute(
                        text("SELECT set_config('app.current_temple_id', :tid, false)"),
                        {"tid": str(temple_id)}
                    )
                else:
                    await session.execute(text("SELECT set_config('app.current_temple_id', '', false)"))
                
                await session.execute(
                    text("SELECT set_config('app.current_role', :role, false)"),
                    {"role": str(user_role)}
                )
            else:
                # Handle background jobs (non-request DB sessions) (Phase 1 Fix #3)
                await session.execute(text("SELECT set_config('app.current_temple_id', 'SYSTEM', false)"))
                await session.execute(text("SELECT set_config('app.current_role', 'SUPER_ADMIN', false)"))

        # Phase 1 Fix: RLS context is set on the session.
        # We don't commit here as it starts a transaction that we might not need yet.
        # Services will start their own transactions via async with db.begin() if needed.

        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
