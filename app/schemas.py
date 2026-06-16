from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class ProductLineCreate(BaseModel):
    name: str
    description: str = ""


class ProductLineOut(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TemplateItemCreate(BaseModel):
    category: str = ""
    name: str
    description: str = ""
    standard: str = ""
    sort_order: int = 0
    is_required: int = 1
    score_weight: float = 1.0


class TemplateItemOut(BaseModel):
    id: int
    template_id: int
    category: str
    name: str
    description: str
    standard: str
    sort_order: int
    is_required: int
    score_weight: float

    class Config:
        from_attributes = True


class TemplateCreate(BaseModel):
    product_line_id: int
    name: str
    description: str = ""
    created_by: str
    items: List[TemplateItemCreate] = []


class TemplateOut(BaseModel):
    id: int
    product_line_id: int
    name: str
    version: int
    description: str
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    items: List[TemplateItemOut] = []

    class Config:
        from_attributes = True


class TemplateVersionOut(BaseModel):
    id: int
    name: str
    version: int
    status: str
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class ExecutionCreate(BaseModel):
    template_id: int
    executor: str


class ExecutionItemScore(BaseModel):
    template_item_id: int
    score: float = 0.0
    max_score: float = 0.0
    result: str = "pending"
    remark: str = ""
    scored_by: str = ""


class ExecutionItemOut(BaseModel):
    id: int
    execution_id: int
    template_item_id: int
    score: float
    max_score: float
    result: str
    remark: str
    scored_by: str
    scored_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ExecutionOut(BaseModel):
    id: int
    template_id: int
    product_line_id: int
    batch_no: str
    status: str
    executor: str
    total_score: float
    max_score: float
    created_at: datetime
    updated_at: datetime
    execution_items: List[ExecutionItemOut] = []

    class Config:
        from_attributes = True


class NonConformanceCreate(BaseModel):
    execution_item_id: int
    description: str
    severity: str = "minor"
    disposition: str = "rework"
    created_by: str


class NonConformanceOut(BaseModel):
    id: int
    execution_item_id: int
    description: str
    severity: str
    disposition: str
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class RectificationCreate(BaseModel):
    action_plan: str
    responsible_person: str
    due_date: Optional[datetime] = None
    remark: str = ""


class RectificationUpdate(BaseModel):
    status: Optional[str] = None
    completed_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    remark: Optional[str] = None


class RectificationOut(BaseModel):
    id: int
    nonconformance_id: int
    action_plan: str
    responsible_person: str
    due_date: Optional[datetime] = None
    status: str
    completed_at: Optional[datetime] = None
    verified_by: str
    verified_at: Optional[datetime] = None
    remark: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ReviewCreate(BaseModel):
    reviewer: str
    result: str
    comment: str = ""


class ReviewOut(BaseModel):
    id: int
    execution_id: int
    reviewer: str
    result: str
    comment: str
    reviewed_at: datetime

    class Config:
        from_attributes = True


class BatchScoreRequest(BaseModel):
    items: List[ExecutionItemScore]


class ExecutionQueryParams(BaseModel):
    product_line_id: Optional[int] = None
    status: Optional[str] = None
    executor: Optional[str] = None
    batch_no: Optional[str] = None
    skip: int = 0
    limit: int = 20
