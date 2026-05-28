"""
System-Level RBAC Models — Platform-wide roles and permissions.

These tables handle cross-cutting platform permissions (APPROVE_TEMPLE,
CREATE_TEMPLE, MANAGE_ROLES) as opposed to the existing tenant-scoped
RBAC in models/rbac.py which handles fine-grained per-temple access
(module/tab/button visibility).

The two RBAC layers coexist:
  - System RBAC → "Can this user approve temples?" (platform-level)
  - Tenant RBAC → "Can this user see the inventory tab?" (temple-level)
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Boolean, DateTime, ForeignKey, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.session import Base


def utcnow():
    return datetime.now(timezone.utc)


class SystemRole(Base):
    """
    Global platform role — e.g. SUPER_ADMIN, TEMPLE_ADMIN, STAFF, DEVOTEE.

    System roles (is_system=True) are seeded at startup and cannot be
    modified or deleted through the admin UI.
    """
    __tablename__ = "system_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, default="")
    is_system = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    permissions = relationship(
        "SystemRolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class SystemPermission(Base):
    """
    A single platform-level permission identified by a unique key.

    Examples: APPROVE_TEMPLE, EDIT_TEMPLE, MANAGE_ROLES, BOOK_OFFERING.
    """
    __tablename__ = "system_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String, unique=True, nullable=False)
    description = Column(Text, default="")
    is_sensitive = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class SystemRolePermission(Base):
    """Links a SystemRole to one or more SystemPermissions."""
    __tablename__ = "system_role_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id = Column(
        UUID(as_uuid=True),
        ForeignKey("system_roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    permission_id = Column(
        UUID(as_uuid=True),
        ForeignKey("system_permissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    role = relationship("SystemRole", back_populates="permissions")
    permission = relationship("SystemPermission", lazy="joined")

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_sys_role_permission"),
    )
