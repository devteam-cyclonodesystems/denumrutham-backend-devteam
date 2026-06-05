import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.models.domain import Employee
from app.core.config import settings
import uuid

async def test():
    engine = create_async_engine(settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://'))
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        emp_id = uuid.uuid4()
        emp = Employee(id=emp_id, temple_id=uuid.uuid4(), name="Test", status="Active")
        print(f"Before add: emp.id = {emp.id}")
        session.add(emp)
        print(f"After add: emp.id = {emp.id}")
        await session.flush()
        print(f"After flush: emp.id = {emp.id}")
        await session.rollback()

if __name__ == "__main__":
    asyncio.run(test())
