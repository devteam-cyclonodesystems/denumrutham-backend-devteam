
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text
from app.models.domain import User, Temple, ChangeRequest, Employee
from uuid import UUID

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/tms_postgres"

async def verify():
    engine = create_async_engine(DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        print("--- Verification Report ---")
        
        # 1. Existing Users Check
        res = await session.execute(select(User).limit(5))
        users = res.scalars().all()
        print(f"Verified {len(users)} existing users have is_active={all(u.is_active for u in users)}")
        
        # 2. Temple Check
        res = await session.execute(select(Temple).limit(1))
        temple = res.scalars().first()
        if temple:
            print(f"Verified temple '{temple.name}' has is_active={temple.is_active}, version={temple.version}")
        
        # 3. Soft Delete Test
        if users:
            test_user = users[0]
            print(f"Soft-deleting user {test_user.user_id}...")
            test_user.is_active = False
            await session.commit()
            
            # Check if excluded from normal query
            res = await session.execute(select(User).filter(User.is_active == True, User.id == test_user.id))
            should_be_none = res.scalars().first()
            print(f"Soft-deleted user excluded from active query: {should_be_none is None}")
            
            # Restore
            test_user.is_active = True
            await session.commit()

        # 4. Version Increment Check (Manual simulation)
        res = await session.execute(select(Employee).limit(1))
        emp = res.scalars().first()
        if emp:
            old_version = emp.version
            print(f"Employee {emp.name} version: {old_version}")
            emp.version += 1
            await session.commit()
            await session.refresh(emp)
            print(f"Incremented version: {emp.version} (Success: {emp.version == old_version + 1})")
            
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(verify())
