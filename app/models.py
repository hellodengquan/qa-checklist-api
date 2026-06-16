import uuid
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey, UniqueConstraint
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
    product_line_id = Column(Integer, ForeignKey("product_lines.id"), nullable=False)
    name = Column(String(200), nullable=False)
    version = Column(Integer, default=1)
    description = Column(Text, default="")
    status = Column(String(20), default="draft")
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product_line = relationship("ProductLine", back_populates="templates")
    items = relationship("TemplateItem", back_populates="template", cascade="all, delete-orphan")
    executions = relationship("Execution", back_populates="template")


class TemplateItem(Base):
    __tablename__ = "template_items"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("checklist_templates.id"), nullable=False)
    category = Column(String(100), default="")
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    standard = Column(Text, default="")
    sort_order = Column(Integer, default=0)
    is_required = Column(Integer, default=1)
    score_weight = Column(Float, default=1.0)

    template = relationship("ChecklistTemplate", back_populates="items")


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (UniqueConstraint("batch_no", name="uq_executions_batch_no"),)

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("checklist_templates.id"), nullable=False)
    product_line_id = Column(Integer, ForeignKey("product_lines.id"), nullable=False)
    batch_no = Column(String(150), unique=True, nullable=False)
    batch_prefix = Column(String(50), default="QA")
    status = Column(String(20), default="in_progress")
    executor = Column(String(100), nullable=False)
    total_score = Column(Float, default=0.0)
    max_score = Column(Float, default=0.0)
    arbitration_result = Column(String(20), nullable=True)
    arbitration_by = Column(String(100), default="")
    arbitration_at = Column(DateTime, nullable=True)
    arbitration_comment = Column(Text, default="")
    force_completed = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    template = relationship("ChecklistTemplate", back_populates="executions")
    product_line = relationship("ProductLine", back_populates="executions")
    execution_items = relationship("ExecutionItem", back_populates="execution", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="execution", cascade="all, delete-orphan")


class ExecutionItem(Base):
    __tablename__ = "execution_items"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=False)
    template_item_id = Column(Integer, ForeignKey("template_items.id"), nullable=False)
    score = Column(Float, default=0.0)
    max_score = Column(Float, default=0.0)
    result = Column(String(20), default="pending")
    remark = Column(Text, default="")
    scored_by = Column(String(100), default="")
    scored_at = Column(DateTime, nullable=True)

    execution = relationship("Execution", back_populates="execution_items")
    template_item = relationship("TemplateItem")
    nonconformance = relationship("NonConformance", back_populates="execution_item", uselist=False, cascade="all, delete-orphan")
    score_revisions = relationship("ScoreRevision", back_populates="execution_item", cascade="all, delete-orphan")


class ScoreRevision(Base):
    __tablename__ = "score_revisions"

    id = Column(Integer, primary_key=True, index=True)
    execution_item_id = Column(Integer, ForeignKey("execution_items.id"), nullable=False)
    old_score = Column(Float, default=0.0)
    new_score = Column(Float, default=0.0)
    old_result = Column(String(20), default="")
    new_result = Column(String(20), default="")
    old_remark = Column(Text, default="")
    new_remark = Column(Text, default="")
    old_max_score = Column(Float, default=0.0)
    new_max_score = Column(Float, default=0.0)
    changed_by = Column(String(100), nullable=False)
    changed_at = Column(DateTime, default=datetime.utcnow)
    reason = Column(Text, default="")

    execution_item = relationship("ExecutionItem", back_populates="score_revisions")


class NonConformance(Base):
    __tablename__ = "nonconformances"

    id = Column(Integer, primary_key=True, index=True)
    execution_item_id = Column(Integer, ForeignKey("execution_items.id"), nullable=False)
    description = Column(Text, nullable=False)
    severity = Column(String(20), default="minor")
    disposition = Column(String(30), default="rework")
    escalation_level = Column(Integer, default=1)
    escalated_from_id = Column(Integer, ForeignKey("nonconformances.id"), nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    execution_item = relationship("ExecutionItem", back_populates="nonconformance")
    rectification = relationship("Rectification", back_populates="nonconformance", uselist=False, cascade="all, delete-orphan")
    escalated_from = relationship("NonConformance", remote_side=[id], foreign_keys=[escalated_from_id])


class Rectification(Base):
    __tablename__ = "rectifications"

    id = Column(Integer, primary_key=True, index=True)
    nonconformance_id = Column(Integer, ForeignKey("nonconformances.id"), nullable=False)
    action_plan = Column(Text, nullable=False)
    responsible_person = Column(String(100), nullable=False)
    due_date = Column(DateTime, nullable=True)
    status = Column(String(20), default="pending")
    completed_at = Column(DateTime, nullable=True)
    verified_by = Column(String(100), default="")
    verified_at = Column(DateTime, nullable=True)
    remark = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    nonconformance = relationship("NonConformance", back_populates="rectification")
    transfers = relationship("RectificationTransfer", back_populates="rectification", cascade="all, delete-orphan")


class RectificationTransfer(Base):
    __tablename__ = "rectification_transfers"

    id = Column(Integer, primary_key=True, index=True)
    rectification_id = Column(Integer, ForeignKey("rectifications.id"), nullable=False)
    from_person = Column(String(100), nullable=False)
    to_person = Column(String(100), nullable=False)
    reason = Column(Text, default="")
    transferred_at = Column(DateTime, default=datetime.utcnow)

    rectification = relationship("Rectification", back_populates="transfers")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=False)
    reviewer = Column(String(100), nullable=False)
    result = Column(String(20), nullable=False)
    comment = Column(Text, default="")
    reviewed_at = Column(DateTime, default=datetime.utcnow)

    execution = relationship("Execution", back_populates="reviews")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(200), default="")
    role = Column(String(30), default="inspector")
    product_line_ids = Column(String(500), default="")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), default="")
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(Integer, default=0)
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


def generate_batch_no(prefix: str = "QA", product_line_id: int = 0) -> str:
    now = datetime.utcnow()
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix}-{now.strftime('%Y%m%d%H%M%S')}-{product_line_id}-{short_uuid}"
