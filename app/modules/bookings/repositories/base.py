import logging
from uuid import UUID as PyUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from typing import Any, Generic, List, Optional, Type, TypeVar
from pydantic import BaseModel
from app.core.database import Base

logger = logging.getLogger("tms.repository")

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


def _to_uuid(value: Any) -> Optional[PyUUID]:
    """Convert a value to a UUID object; return None if invalid or None."""
    if value is None:
        return None
    if isinstance(value, PyUUID):
        return value
    try:
        return PyUUID(str(value))
    except (ValueError, AttributeError):
        return None


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: Type[ModelType]):
        self.model = model

    async def get(self, db: AsyncSession, id: Any) -> Optional[ModelType]:
        result = await db.execute(select(self.model).filter(self.model.id == _to_uuid(id)))
        return result.scalars().first()

    async def get_multi_by_temple(
        self, db: AsyncSession, temple_id: Any, skip: int = 0, limit: int = 100
    ) -> List[ModelType]:
        tid = _to_uuid(temple_id)
        if temple_id is not None and tid is None:
            # If a temple_id was provided but it's not a valid UUID, return empty list
            # instead of crashing with a DataError (e.g. for 'TEMP001')
            logger.warning("Invalid temple_id format provided: %s", temple_id)
            return []

        result = await db.execute(
            select(self.model)
            .filter(self.model.temple_id == tid)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def create(
        self, db: AsyncSession, *, obj_in: CreateSchemaType, temple_id: Any = None
    ) -> ModelType:
        obj_in_data = obj_in.model_dump()
        if temple_id:
            obj_in_data["temple_id"] = _to_uuid(temple_id)
        # Convert any UUID-string fields to proper UUID objects
        for key, val in obj_in_data.items():
            if isinstance(val, str):
                try:
                    PyUUID(val)  # test if it's a uuid string
                    obj_in_data[key] = PyUUID(val)
                except (ValueError, AttributeError):
                    pass
        db_obj = self.model(**obj_in_data)
        db.add(db_obj)
        try:
            await db.commit()
            await db.refresh(db_obj)
        except IntegrityError:
            await db.rollback()
            logger.error("IntegrityError creating %s", self.model.__tablename__)
            raise
        return db_obj

    async def create_audit_log(
        self,
        db: AsyncSession,
        *,
        temple_id: Any,
        user_id: Any,
        action: str,
        details: str,
    ):
        from app.models.domain import AuditLog

        log = AuditLog(
            temple_id=_to_uuid(temple_id),
            user_id=_to_uuid(user_id),
            action=action,
            details=details,
        )
        db.add(log)
        await db.commit()
