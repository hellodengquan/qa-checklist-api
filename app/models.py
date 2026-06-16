import uuid
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey, UniqueConstraint, Index, JSON
)
from sqlalchemy.orm import relationship
from app.database import Base


class ProductLine(Base):
    __tablename__ = "product_lines"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    templates = relationship("ChecklistTemplate", back_populates="product_line")
    executions = relationship("Execution", back_populates="product_line")


class ChecklistTemplate(Base):
    __tablename__ = "checklist_templates"

    id = Column(Integer, primary_key=True, index=True)
    product_line_id = Column(Integer, ForeignKey("product_lines.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False, index=True)
    version = Column(Integer, default=1)
    description = Column(Text, default="")
    status = Column(String(20), default="draft")
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product_line = relationship("ProductLine", back_populates="templates")
    items = relationship("TemplateItem", back_populates="template", cascade="all, delete-orphan")
    executions = relationship("Execution", back_populates="template")

    __table_args__ = (
        Index("idx_tpl_productline_name", "product_line_id", "name"),
        Index("idx_tpl_status", "status"),
    )


class TemplateItem(Base):
    __tablename__ = "template_items"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("checklist_templates.id"), nullable=False, index=True)
    category = Column(String(100), default="", index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    standard = Column(Text, default="")
    sort_order = Column(Integer, default=0)
    is_required = Column(Integer, default=1)
    score_weight = Column(Float, default=1.0)

    template = relationship("ChecklistTemplate", back_populates="items")


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (
        UniqueConstraint("batch_no", name="uq_executions_batch_no"),
        Index("idx_exec_productline_status", "product_line_id", "status"),
        Index("idx_exec_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("checklist_templates.id"), nullable=False, index=True)
    product_line_id = Column(Integer, ForeignKey("product_lines.id"), nullable=False, index=True)
    batch_no = Column(String(150), unique=True, nullable=False, index=True)
    batch_prefix = Column(String(50), default="QA")
    status = Column(String(20), default="in_progress", index=True)
    executor = Column(String(100), nullable=False, index=True)
    total_score = Column(Float, default=0.0)
    max_score = Column(Float, default=0.0)
    arbitration_result = Column(String(20), nullable=True)
    arbitration_by = Column(String(100), default="")
    arbitration_at = Column(DateTime, nullable=True)
    arbitration_comment = Column(Text, default="")
    force_completed = Column(Integer, default=0)
    suspended_by = Column(String(100), default="")
    suspended_at = Column(DateTime, nullable=True)
    suspend_reason = Column(Text, default="")
    terminated_by = Column(String(100), default="")
    terminated_at = Column(DateTime, nullable=True)
    terminate_reason = Column(Text, default="")
    last_revision_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    template = relationship("ChecklistTemplate", back_populates="executions")
    product_line = relationship("ProductLine", back_populates="executions")
    execution_items = relationship("ExecutionItem", back_populates="execution", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="execution", cascade="all, delete-orphan")


class ExecutionItem(Base):
    __tablename__ = "execution_items"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=False, index=True)
    template_item_id = Column(Integer, ForeignKey("template_items.id"), nullable=False, index=True)
    score = Column(Float, default=0.0)
    max_score = Column(Float, default=0.0)
    result = Column(String(20), default="pending", index=True)
    remark = Column(Text, default="")
    scored_by = Column(String(100), default="")
    scored_at = Column(DateTime, nullable=True)

    execution = relationship("Execution", back_populates="execution_items")
    template_item = relationship("TemplateItem")
    nonconformance = relationship("NonConformance", back_populates="execution_item", uselist=False, cascade="all, delete-orphan")
    score_revisions = relationship("ScoreRevision", back_populates="execution_item", cascade="all, delete-orphan")


class ScoreRevision(Base):
    __tablename__ = "score_revisions"
    __table_args__ = (
        Index("idx_srev_exec_item_time", "execution_item_id", "changed_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    execution_item_id = Column(Integer, ForeignKey("execution_items.id"), nullable=False, index=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=True, index=True)
    old_score = Column(Float, default=0.0)
    new_score = Column(Float, default=0.0)
    old_result = Column(String(20), default="")
    new_result = Column(String(20), default="")
    old_remark = Column(Text, default="")
    new_remark = Column(Text, default="")
    old_max_score = Column(Float, default=0.0)
    new_max_score = Column(Float, default=0.0)
    changed_by = Column(String(100), nullable=False, index=True)
    changed_at = Column(DateTime, default=datetime.utcnow, index=True)
    reason = Column(Text, default="")
    revision_group = Column(String(50), default="")
    snapshot = Column(JSON, nullable=True)

    execution_item = relationship("ExecutionItem", back_populates="score_revisions")


class NonConformance(Base):
    __tablename__ = "nonconformances"
    __table_args__ = (
        Index("idx_nc_severity", "severity"),
        Index("idx_nc_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    execution_item_id = Column(Integer, ForeignKey("execution_items.id"), nullable=False, index=True)
    description = Column(Text, nullable=False)
    severity = Column(String(20), default="minor", index=True)
    disposition = Column(String(30), default="rework")
    escalation_level = Column(Integer, default=1)
    escalated_from_id = Column(Integer, ForeignKey("nonconformances.id"), nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    execution_item = relationship("ExecutionItem", back_populates="nonconformance")
    rectification = relationship("Rectification", back_populates="nonconformance", uselist=False, cascade="all, delete-orphan")
    escalated_from = relationship("NonConformance", remote_side=[id], foreign_keys=[escalated_from_id])


class NCEscalationRule(Base):
    __tablename__ = "nc_escalation_rules"

    id = Column(Integer, primary_key=True, index=True)
    product_line_id = Column(Integer, ForeignKey("product_lines.id"), nullable=True, index=True)
    trigger_type = Column(String(30), default="recurring_count")
    trigger_value = Column(Integer, default=3)
    from_severity = Column(String(20), default="minor")
    to_severity = Column(String(20), default="major")
    window_days = Column(Integer, default=30)
    rule_name = Column(String(200), default="")
    is_active = Column(Integer, default=1)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class Rectification(Base):
    __tablename__ = "rectifications"
    __table_args__ = (
        Index("idx_rect_status_person", "status", "responsible_person"),
        Index("idx_rect_due_date", "due_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    nonconformance_id = Column(Integer, ForeignKey("nonconformances.id"), nullable=False, index=True)
    action_plan = Column(Text, nullable=False)
    responsible_person = Column(String(100), nullable=False, index=True)
    due_date = Column(DateTime, nullable=True, index=True)
    status = Column(String(20), default="pending", index=True)
    completed_at = Column(DateTime, nullable=True)
    verified_by = Column(String(100), default="")
    verified_at = Column(DateTime, nullable=True)
    remark = Column(Text, default="")
    pending_transfer_id = Column(Integer, ForeignKey("rectification_transfers.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    nonconformance = relationship("NonConformance", back_populates="rectification")
    transfers = relationship("RectificationTransfer", back_populates="rectification", cascade="all, delete-orphan",
                             foreign_keys="RectificationTransfer.rectification_id")


class RectificationTransfer(Base):
    __tablename__ = "rectification_transfers"

    id = Column(Integer, primary_key=True, index=True)
    rectification_id = Column(Integer, ForeignKey("rectifications.id"), nullable=False, index=True)
    from_person = Column(String(100), nullable=False)
    to_person = Column(String(100), nullable=False)
    reason = Column(Text, default="")
    transferred_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="completed")
    approver = Column(String(100), default="")
    approved_at = Column(DateTime, nullable=True)
    approval_comment = Column(Text, default="")
    requested_by = Column(String(100), default="")
    requested_at = Column(DateTime, default=datetime.utcnow)

    rectification = relationship("Rectification", back_populates="transfers", foreign_keys=[rectification_id])


class TransferApproval(Base):
    __tablename__ = "transfer_approvals"

    id = Column(Integer, primary_key=True, index=True)
    transfer_id = Column(Integer, ForeignKey("rectification_transfers.id"), nullable=False, index=True)
    approver = Column(String(100), nullable=False)
    decision = Column(String(20), nullable=False)
    comment = Column(Text, default="")
    approved_at = Column(DateTime, default=datetime.utcnow)


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        Index("idx_reviews_exec_result", "execution_id", "result"),
    )

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=False, index=True)
    reviewer = Column(String(100), nullable=False, index=True)
    result = Column(String(20), nullable=False, index=True)
    comment = Column(Text, default="")
    reviewed_at = Column(DateTime, default=datetime.utcnow)

    execution = relationship("Execution", back_populates="reviews")


class ArbitrationConsensus(Base):
    __tablename__ = "arbitration_consensus"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=False, index=True)
    voter = Column(String(100), nullable=False)
    vote = Column(String(20), nullable=False)
    comment = Column(Text, default="")
    voted_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    display_name = Column(String(200), default="")
    role = Column(String(30), default="inspector", index=True)
    product_line_ids = Column(String(500), default="")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RBACMatrix(Base):
    __tablename__ = "rbac_matrix"
    __table_args__ = (
        UniqueConstraint("role", "resource", "action", name="uq_rbac_role_resource_action"),
    )

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(30), nullable=False, index=True)
    resource = Column(String(50), nullable=False, index=True)
    action = Column(String(30), nullable=False, index=True)
    description = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_log_user_action_time", "username", "action", "created_at"),
        Index("idx_log_resource", "resource_type", "resource_id"),
        Index("idx_log_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), default="", index=True)
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False, index=True)
    resource_id = Column(Integer, default=0, index=True)
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


def generate_batch_no(prefix: str = "QA", product_line_id: int = 0) -> str:
    now = datetime.utcnow()
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix}-{now.strftime('%Y%m%d%H%M%S')}-{product_line_id}-{short_uuid}"
