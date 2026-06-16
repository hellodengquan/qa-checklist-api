from datetime import datetime
from typing import Optional, List, Dict, Any
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
    suspended_by: str = ""
    suspended_at: Optional[datetime] = None
    suspend_reason: str = ""
    terminated_by: str = ""
    terminated_at: Optional[datetime] = None
    terminate_reason: str = ""
    last_revision_id: Optional[int] = None
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


class NCEscalationRuleCreate(BaseModel):
    product_line_id: Optional[int] = None
    trigger_type: str = "recurring_count"
    trigger_value: int = 3
    from_severity: str = "minor"
    to_severity: str = "major"
    window_days: int = 30
    rule_name: str = ""
    created_by: str = ""


class NCEscalationRuleOut(BaseModel):
    id: int
    product_line_id: Optional[int] = None
    trigger_type: str
    trigger_value: int
    from_severity: str
    to_severity: str
    window_days: int
    rule_name: str
    is_active: int
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
    pending_transfer_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RectificationTransferCreate(BaseModel):
    to_person: str
    reason: str = ""
    requested_by: str = ""


class RectificationTransferOut(BaseModel):
    id: int
    rectification_id: int
    from_person: str
    to_person: str
    reason: str
    transferred_at: Optional[datetime] = None
    status: str
    approver: str = ""
    approved_at: Optional[datetime] = None
    approval_comment: str = ""
    requested_by: str = ""
    requested_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TransferApprovalRequest(BaseModel):
    approver: str
    decision: str
    comment: str = ""


class TransferApprovalOut(BaseModel):
    id: int
    transfer_id: int
    approver: str
    decision: str
    comment: str
    approved_at: datetime

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


class ConsensusVote(BaseModel):
    voter: str
    vote: str
    comment: str = ""


class ConsensusOut(BaseModel):
    id: int
    execution_id: int
    voter: str
    vote: str
    comment: str
    voted_at: datetime

    class Config:
        from_attributes = True


class ConsensusCheckRequest(BaseModel):
    threshold_ratio: Optional[float] = None
    min_voters: Optional[int] = None
    final_decision_maker: Optional[str] = None


class BatchScoreRequest(BaseModel):
    items: List[ExecutionItemScore]


class ScoreRevisionOut(BaseModel):
    id: int
    execution_item_id: int
    execution_id: Optional[int] = None
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
    revision_group: str = ""
    snapshot: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class ScoreReplayRequest(BaseModel):
    revision_ids: List[int] = []
    revision_group: str = ""
    operated_by: str
    reason: str = ""


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


class SuspendRequest(BaseModel):
    operated_by: str
    reason: str = ""


class TerminateRequest(BaseModel):
    operated_by: str
    reason: str = ""


class TemplateMigrateRequest(BaseModel):
    operated_by: str


class TemplateRollbackRequest(BaseModel):
    target_version: int
    operated_by: str


class TemplateCostEstimateOut(BaseModel):
    template_id: int
    template_name: str
    from_version: int
    to_version: int
    affected_in_progress: int
    affected_completed: int
    affected_total: int
    item_diff_added: int
    item_diff_removed: int
    item_diff_modified: int
    complexity_score: int
    risk_level: str
    recommendation: str


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


class RBACEntryCreate(BaseModel):
    role: str
    resource: str
    action: str
    description: str = ""


class RBACEntryOut(BaseModel):
    id: int
    role: str
    resource: str
    action: str
    description: str
    created_at: datetime

    class Config:
        from_attributes = True


class RBACMatrixOut(BaseModel):
    role: str
    permissions: List[Dict[str, str]] = []


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


class AuditLogAggOut(BaseModel):
    date: str
    username: str
    action: str
    count: int


# ============ 第二轮 8 个 Feature ============

class ScoreReplayConcurrencyRequest(BaseModel):
    revision_ids: List[int] = []
    revision_group: str = ""
    held_by: str
    ttl_seconds: int = 300


class ScoreReplayConcurrencyOut(BaseModel):
    id: int
    execution_id: int
    replay_token: str
    revision_ids: str
    revision_group: str
    held_by: str
    held_at: datetime
    expires_at: Optional[datetime] = None
    status: str

    class Config:
        from_attributes = True


class TransferChainCreate(BaseModel):
    transfer_id: int
    approvers: List[str]
    mode: str = "serial"


class TransferChainStepOut(BaseModel):
    id: int
    transfer_id: int
    approver: str
    step_index: int
    decision: str
    comment: str
    decided_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TransferChainApproveRequest(BaseModel):
    approver: str
    decision: str
    comment: str = ""


class DeadLetterArchiveRequest(BaseModel):
    reason: str = ""
    execution_ids: List[int] = []


class DeadLetterArchiveOut(BaseModel):
    id: int
    execution_id: int
    batch_no: str
    original_status: str
    dead_letter_reason: str
    archived_by: str
    archived_at: datetime

    class Config:
        from_attributes = True


class NCThresholdTuningRequest(BaseModel):
    product_line_id: Optional[int] = None
    severity: str = "minor"
    trigger_type: str = "overdue_days"
    window_days: int = 30
    apply_recommendation: bool = False


class NCThresholdTuningOut(BaseModel):
    id: int
    product_line_id: Optional[int] = None
    severity: str
    trigger_type: str
    current_value: float
    recommended_value: float
    confidence: float
    sample_size: int
    analysis_window_days: int
    analyzed_by: str
    analyzed_at: datetime
    detail: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class MigrationBatchCreate(BaseModel):
    from_template_id: int
    to_template_id: int
    strategy: str = "time_window"
    batch_size: int = 100
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None


class MigrationBatchOut(BaseModel):
    id: int
    from_template_id: int
    to_template_id: int
    strategy: str
    batch_size: int
    time_window_start: Optional[datetime] = None
    time_window_end: Optional[datetime] = None
    total_target: int
    total_processed: int
    total_failed: int
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RBACProfileCreate(BaseModel):
    name: str
    description: str = ""
    entries: List[Dict[str, Any]] = []


class RBACProfileOut(BaseModel):
    id: int
    name: str
    description: str
    is_active: int
    activated_by: str
    activated_at: Optional[datetime] = None
    entries: Optional[List[Dict[str, Any]]] = None
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class IndexStatsCaptureRequest(BaseModel):
    sample_queries: Optional[Dict[str, str]] = None


class IndexStatsOut(BaseModel):
    id: int
    table_name: str
    index_name: str
    seq_scan: int
    seq_scan_rows: int
    idx_scan: int
    idx_scan_rows: int
    idx_size_bytes: int
    sample_query: str
    explain_plan: str
    captured_at: datetime

    class Config:
        from_attributes = True


ExecutionOut.model_rebuild()
