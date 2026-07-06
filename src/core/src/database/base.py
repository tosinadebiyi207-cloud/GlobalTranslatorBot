"""
Database base classes with async support.
"""

import asyncio
from typing import Optional, Any, Dict, List, Type, TypeVar
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    AsyncEngine,
    async_sessionmaker,
    async_scoped_session
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool
from sqlalchemy import text
from src.core.config import get_config
from src.core.exceptions import DatabaseError

Base = declarative_base()
T = TypeVar('T', bound=Base)

class DatabaseManager:
    """Async database manager with connection pooling."""
    
    _instance: Optional['DatabaseManager'] = None
    _engine: Optional[AsyncEngine] = None
    _session_factory: Optional[async_sessionmaker] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def initialize(self):
        """Initialize database connection."""
        if self._engine is not None:
            return
        
        config = get_config()
        
        # Convert SQLite URL for async
        database_url = config.DATABASE_URL
        if database_url.startswith('sqlite:///'):
            database_url = database_url.replace('sqlite:///', 'sqlite+aiosqlite:///')
        else:
            database_url = database_url.replace('postgresql://', 'postgresql+asyncpg://')
        
        # Create async engine
        self._engine = create_async_engine(
            database_url,
            pool_size=config.DATABASE_POOL_SIZE,
            max_overflow=config.DATABASE_MAX_OVERFLOW,
            pool_timeout=30,
            pool_recycle=3600,
            echo=config.is_development,
            poolclass=AsyncAdaptedQueuePool
        )
        
        # Create session factory
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False
        )
        
        # Create tables
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    @asynccontextmanager
    async def get_session(self) -> AsyncSession:
        """Get database session."""
        if self._session_factory is None:
            await self.initialize()
        
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception as e:
                await session.rollback()
                raise DatabaseError(f"Database operation failed: {e}") from e
            finally:
                await session.close()
    
    async def close(self):
        """Close database connections."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
    
    async def health_check(self) -> bool:
        """Check database health."""
        try:
            async with self.get_session() as session:
                await session.execute(text("SELECT 1"))
                return True
        except Exception:
            return False

# Global database manager instance
db_manager = DatabaseManager()

@asynccontextmanager
async def get_db():
    """Get database session context manager."""
    async with db_manager.get_session() as session:
        yield session
