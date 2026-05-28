"""Employee Service — Employee/Leave CRUD + Payroll with automatic transaction creation."""
import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.models.domain import Employee, Leave
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, LeaveCreate, LeaveUpdate
from app.services.transaction_service import TransactionService

logger = logging.getLogger("tms.services.employee")


class EmployeeService:

    # --- Employees ---
    @staticmethod
    async def create_employee(db: AsyncSession, emp_in: EmployeeCreate, temple_id: str) -> Employee:
        tid = UUID(str(temple_id))

        # Auto-generate emp_code
        count_result = await db.execute(
            select(func.count(Employee.id)).filter(Employee.temple_id == tid)
        )
        count = count_result.scalar() or 0
        emp_code = f"EMP-{str(count + 1).zfill(3)}"

        emp = Employee(
            temple_id=tid,
            emp_code=emp_code,
            name=emp_in.name,
            role=emp_in.role,
            department=emp_in.department,
            phone=emp_in.phone,
            salary=emp_in.salary,
            join_date=emp_in.join_date,
            status="Active",
            attendance=0,
            remarks=emp_in.remarks,
            promotion_history=[],
            salary_history=[],
        )
        db.add(emp)
        await db.commit()
        await db.refresh(emp)
        return emp

    @staticmethod
    async def get_employees(db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 200):
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(Employee)
            .filter(Employee.temple_id == tid)
            .order_by(Employee.created_at)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def update_employee(
        db: AsyncSession, emp_id: str, update_in: EmployeeUpdate, temple_id: str
    ) -> Employee:
        tid = UUID(str(temple_id))
        eid = UUID(str(emp_id))
        result = await db.execute(
            select(Employee).filter(Employee.id == eid, Employee.temple_id == tid)
        )
        emp = result.scalars().first()
        if not emp:
            return None

        update_data = update_in.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(emp, key, value)

        await db.commit()
        await db.refresh(emp)
        return emp

    @staticmethod
    async def delete_employee(db: AsyncSession, emp_id: str, temple_id: str) -> bool:
        tid = UUID(str(temple_id))
        eid = UUID(str(emp_id))
        result = await db.execute(
            select(Employee).filter(Employee.id == eid, Employee.temple_id == tid)
        )
        emp = result.scalars().first()
        if emp:
            await db.delete(emp)
            await db.commit()
            return True
        return False

    @staticmethod
    async def get_employee_count(db: AsyncSession, temple_id: str) -> int:
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(func.count(Employee.id)).filter(Employee.temple_id == tid)
        )
        return result.scalar() or 0

    # --- Leaves ---
    @staticmethod
    async def create_leave(db: AsyncSession, leave_in: LeaveCreate, temple_id: str) -> Leave:
        tid = UUID(str(temple_id))

        count_result = await db.execute(
            select(func.count(Leave.id)).filter(Leave.temple_id == tid)
        )
        count = count_result.scalar() or 0
        leave_code = f"LV-{str(count + 1).zfill(3)}"

        leave = Leave(
            temple_id=tid,
            employee_id=leave_in.employee_id,
            leave_code=leave_code,
            emp_name=leave_in.emp_name,
            type=leave_in.type,
            from_date=leave_in.from_date,
            to_date=leave_in.to_date,
            reason=leave_in.reason,
            status="pending",
            remarks="",
        )
        db.add(leave)
        await db.commit()
        await db.refresh(leave)
        return leave

    @staticmethod
    async def get_leaves(db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 200):
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(Leave)
            .filter(Leave.temple_id == tid)
            .order_by(Leave.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def update_leave(
        db: AsyncSession, leave_id: str, update_in: LeaveUpdate, temple_id: str
    ) -> Leave:
        tid = UUID(str(temple_id))
        lid = UUID(str(leave_id))
        result = await db.execute(
            select(Leave).filter(Leave.id == lid, Leave.temple_id == tid)
        )
        leave = result.scalars().first()
        if not leave:
            return None

        update_data = update_in.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(leave, key, value)

        await db.commit()
        await db.refresh(leave)
        return leave

    # --- Payroll ---
    @staticmethod
    async def run_payroll(db: AsyncSession, temple_id: str):
        """🔥 TRANSACTION ENGINE: Run payroll → create expense transaction for total salaries."""
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(Employee).filter(Employee.temple_id == tid, Employee.status == "Active")
        )
        employees = result.scalars().all()

        total = sum(e.salary for e in employees)
        if total <= 0:
            return {"total_amount": 0, "employee_count": 0, "transaction_id": None}

        txn = await TransactionService.create_transaction(
            db=db,
            temple_id=temple_id,
            txn_type="expense",
            category="salary",
            amount=total,
            description=f"Monthly Payroll - {len(employees)} employees",
            reference_id="PAYROLL",
            source="system",
        )
        await db.commit()

        return {
            "total_amount": total,
            "employee_count": len(employees),
            "transaction_id": txn.id,
        }
