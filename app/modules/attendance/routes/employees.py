"""Employee & Leave & Payroll API endpoints with strict tenant enforcement."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID
from app.api.deps import get_db, get_current_user, get_current_temple_id, enforce_management_mode
from app.schemas.domain import TokenData
from app.schemas.employee import (
    EmployeeCreate, EmployeeResponse, EmployeeUpdate,
    LeaveCreate, LeaveResponse, LeaveUpdate, PayrollRunResponse,
)
from app.services.employee_service import EmployeeService

router = APIRouter(dependencies=[Depends(enforce_management_mode("hr-payroll"))])


# --- Employees ---
@router.post("", response_model=EmployeeResponse)
async def create_employee(
    emp_in: EmployeeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await EmployeeService.create_employee(
        db=db, emp_in=emp_in, temple_id=temple_id,
        user_id=UUID(str(current_user.sub)) if current_user and current_user.sub else None
    )


@router.get("", response_model=List[EmployeeResponse])
async def list_employees(
    skip: int = 0,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await EmployeeService.get_employees(db=db, temple_id=temple_id, skip=skip, limit=limit)


@router.put("/{emp_id}", response_model=EmployeeResponse)
async def update_employee(
    emp_id: str,
    update_in: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await EmployeeService.update_employee(
        db=db, emp_id=emp_id, update_in=update_in, temple_id=temple_id,
        user_id=UUID(str(current_user.sub)) if current_user and current_user.sub else None
    )
    if not result:
        raise HTTPException(status_code=404, detail="Employee not found")
    return result


@router.delete("/{emp_id}")
async def delete_employee(
    emp_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    success = await EmployeeService.delete_employee(
        db=db, emp_id=emp_id, temple_id=temple_id,
        user_id=UUID(str(current_user.sub)) if current_user and current_user.sub else None
    )
    if not success:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"detail": "Employee deleted"}


# --- Leaves ---
@router.post("/leaves", response_model=LeaveResponse)
async def create_leave(
    leave_in: LeaveCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await EmployeeService.create_leave(
        db=db, leave_in=leave_in, temple_id=temple_id,
        user_id=UUID(str(current_user.sub)) if current_user and current_user.sub else None
    )


@router.get("/leaves", response_model=List[LeaveResponse])
async def list_leaves(
    skip: int = 0,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await EmployeeService.get_leaves(db=db, temple_id=temple_id, skip=skip, limit=limit)


@router.patch("/leaves/{leave_id}/approve", response_model=LeaveResponse)
async def approve_leave(
    leave_id: str,
    update_in: LeaveUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    update_in.status = "approved"
    result = await EmployeeService.update_leave(
        db=db, leave_id=leave_id, update_in=update_in, temple_id=temple_id,
        user_id=UUID(str(current_user.sub)) if current_user and current_user.sub else None
    )
    if not result:
        raise HTTPException(status_code=404, detail="Leave not found")
    return result


@router.patch("/leaves/{leave_id}/reject", response_model=LeaveResponse)
async def reject_leave(
    leave_id: str,
    update_in: LeaveUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    update_in.status = "rejected"
    result = await EmployeeService.update_leave(
        db=db, leave_id=leave_id, update_in=update_in, temple_id=temple_id,
        user_id=UUID(str(current_user.sub)) if current_user and current_user.sub else None
    )
    if not result:
        raise HTTPException(status_code=404, detail="Leave not found")
    return result


# --- Payroll ---
@router.post("/payroll/run")
async def run_payroll(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await EmployeeService.run_payroll(
        db=db, temple_id=temple_id,
        user_id=UUID(str(current_user.sub)) if current_user and current_user.sub else None
    )
