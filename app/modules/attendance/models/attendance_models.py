import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Float, Text, Enum, Integer, Time, UniqueConstraint, Date, JSON, Index, text, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database.database import Base

def utcnow():
    return datetime.now(timezone.utc)


class Employee(Base):
    """Temple employee record."""
    __tablename__ = "employees"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    emp_code = Column(String, nullable=True)  # e.g. EMP-001
    name = Column(String, nullable=False)
    role = Column(String, default="")
    department = Column(String, default="")
    phone = Column(String, default="")
    salary = Column(Float, default=0.0)
    join_date = Column(String, default="")
    attendance = Column(Integer, default=0)
    status = Column(String, default="Active")  # Active | On Leave | Offboarded
    is_active = Column(Boolean, default=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    remarks = Column(Text, default="")
    promotion_history = Column(JSON, default=list)
    salary_history = Column(JSON, default=list)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)




class Leave(Base):
    """Employee leave request."""
    __tablename__ = "leaves"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=False)
    leave_code = Column(String, nullable=True)  # e.g. LV-001
    emp_name = Column(String, default="")  # denormalized for UI
    type = Column(String, default="Casual")  # Casual | Sick | Earned | Half Day
    from_date = Column(String, nullable=False)
    to_date = Column(String, nullable=False)
    reason = Column(Text, default="")
    status = Column(String, default="pending")  # pending | approved | rejected
    remarks = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


