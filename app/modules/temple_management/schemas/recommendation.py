"""
Service Recommendation Schemas.
"""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class ServiceRecommendationBase(BaseModel):
    source_service_id: Optional[UUID] = None
    source_product_id: Optional[UUID] = None
    recommendation_source_type: str = Field(default="SERVICE", pattern="^(SERVICE|PRODUCT)$")
    recommended_service_id: Optional[UUID] = None
    recommended_product_id: Optional[UUID] = None
    display_order: int = 0
    is_active: bool = True

    @model_validator(mode="after")
    def validate_source_and_target(self) -> 'ServiceRecommendationBase':
        source_service = self.source_service_id
        source_product = self.source_product_id
        rec_service = self.recommended_service_id
        rec_product = self.recommended_product_id

        if source_service is None and source_product is None:
            raise ValueError("Must specify either source_service_id or source_product_id")
        if source_service is not None and source_product is not None:
            raise ValueError("Cannot specify both source_service_id and source_product_id")

        if rec_service is None and rec_product is None:
            raise ValueError("Must specify either recommended_service_id or recommended_product_id")
        if rec_service is not None and rec_product is not None:
            raise ValueError("Cannot specify both recommended_service_id and recommended_product_id")

        # Validate recommendation_source_type matches actual source set
        if source_service is not None and self.recommendation_source_type != "SERVICE":
            raise ValueError("recommendation_source_type must be SERVICE when source_service_id is set")
        if source_product is not None and self.recommendation_source_type != "PRODUCT":
            raise ValueError("recommendation_source_type must be PRODUCT when source_product_id is set")

        return self


class ServiceRecommendationCreate(ServiceRecommendationBase):
    pass


class ServiceRecommendationUpdate(BaseModel):
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class TempleServiceMin(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    service_name: str
    price: float


class StoreProductMin(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    unit_price: float
    category: str


class ServiceRecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    temple_id: UUID
    source_service_id: Optional[UUID] = None
    source_product_id: Optional[UUID] = None
    recommendation_source_type: str
    recommended_service_id: Optional[UUID] = None
    recommended_product_id: Optional[UUID] = None
    display_order: int
    is_active: bool
    created_at: datetime

    recommended_service: Optional[TempleServiceMin] = None
    recommended_product: Optional[StoreProductMin] = None


class PublicRecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    recommendation_type: str  # 'SERVICE' or 'PRODUCT'
    display_order: int
    service: Optional[TempleServiceMin] = None
    product: Optional[StoreProductMin] = None


class PublicResolverPayload(BaseModel):
    source_type: str
    source_id: UUID
    recommendations: List[PublicRecommendationResponse]
