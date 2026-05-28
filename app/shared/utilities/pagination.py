"""
Global pagination dependency for all list endpoints.
"""
from fastapi import Query
from dataclasses import dataclass


@dataclass
class PaginationParams:
    """Standard pagination parameters extracted from query string."""
    page: int
    page_size: int
    offset: int

    @property
    def limit(self) -> int:
        return self.page_size


def get_pagination(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
) -> PaginationParams:
    """FastAPI dependency for standard pagination."""
    return PaginationParams(
        page=page,
        page_size=page_size,
        offset=(page - 1) * page_size,
    )
