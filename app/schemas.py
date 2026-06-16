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
    batch_prefix: str = "QA"


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
    batch_prefix: str
    status: str
    executor: str
    total_score: float
    max_score: float
    arbitration_result: Optional[str] = None
    arbitration_by: str = ""
    arbitration_at: Optional[datetime] = None
    arbitration_comment: str = ""
    force_completed: int = 0
    created_at: datetime
    updated_at: datetime
    execution_items: List[ExecutionItemOut] = []
    reviews: List["ReviewOut"] = []

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
    escalation_level: int
    escalated_from_id: Optional[int] = None
    escalated_at: Optional[datetime] = None
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class NonConformanceEscalate(BaseModel):
    escalated_by: str
    reason: str = ""


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


class RectificationTransferCreate(BaseModel):
    to_person: str
    reason: str = ""


class RectificationTransferOut(BaseModel):
    id: int
    rectification_id: int
    from_person: str
    to_person: str
    reason: str
    transferred_at: datetime

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


class ArbitrationRequest(BaseModel):
    arbitrator: str
    result: str
    comment: str = ""


class BatchScoreRequest(BaseModel):
    items: List[ExecutionItemScore]


class ScoreRevisionOut(BaseModel):
    id: int
    execution_item_id: int
    old_score: float
    new_score: float
    old_result: str
    new_result: str
    old_remark: str
    new_remark: str
    old_max_score: float
    new_max_score: float
    changed_by: str
    changed_at: datetime
    reason: str

    class Config:
        from_attributes = True


class ScoreModifyRequest(BaseModel):
    items: List[ExecutionItemScore]
    changed_by: str
    reason: str = ""


class ForceCompleteRequest(BaseModel):
    operated_by: str
    reason: str = ""


class ReopenRequest(BaseModel):
    operated_by: str
    reason: str = ""


class TemplateMigrateRequest(BaseModel):
    operated_by: str


class TemplateRollbackRequest(BaseModel):
    target_version: int
    operated_by: str


class UserCreate(BaseModel):
    username: str
    display_name: str = ""
    role: str = "inspector"
    product_line_ids: List[int] = []


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    product_line_ids: Optional[List[int]] = None
    is_active: Optional[int] = None


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    product_line_ids: str
    is_active: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AuditLogOut(BaseModel):
    id: int
    username: str
    action: str
    resource_type: str
    resource_id: int
    detail: str
    created_at: datetime

    class Config:
        from_attributes = True


ExecutionOut.model_rebuild()
