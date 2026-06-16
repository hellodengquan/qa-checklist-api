from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    Execution, ExecutionItem, ChecklistTemplate, TemplateItem,
    NonConformance, ScoreRevision, AuditLog, generate_batch_no,
)
from app.schemas import (
    ExecutionCreate, ExecutionOut, ExecutionItemScore,
    BatchScoreRequest, NonConformanceCreate, NonConformanceOut,
    NonConformanceEscalate, ScoreModifyRequest, ScoreRevisionOut,
    ForceCompleteRequest, ReopenRequest,
)

router = APIRouter(prefix="/api/executions", tags=["执行记录"])

SEVERITY_LADDER = ["minor", "major", "critical"]


def _log(db: Session, username: str, action: str, rtype: str, rid: int, detail: str = ""):
    db.add(AuditLog(username=username, action=action, resource_type=rtype, resource_id=rid, detail=detail))


@router.post("", response_model=ExecutionOut)
def create_execution(data: ExecutionCreate, db: Session = Depends(get_db)):
    tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == data.template_id).first()
    if not tpl:
        raise HTTPException(status_code=400, detail="模板不存在")
    if tpl.status != "active":
        raise HTTPException(status_code=400, detail="只有激活状态的模板才能创建执行记录")
    prefix = data.batch_prefix.strip() or "QA"
    max_score = sum(item.score_weight for item in tpl.items)
    max_retries = 5
    for _ in range(max_retries):
        batch_no = generate_batch_no(prefix=prefix, product_line_id=tpl.product_line_id)
        execution = Execution(
            template_id=data.template_id,
            product_line_id=tpl.product_line_id,
            batch_no=batch_no,
            batch_prefix=prefix,
            status="in_progress",
            executor=data.executor,
            total_score=0.0,
            max_score=max_score,
        )
        db.add(execution)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            continue
    else:
        raise HTTPException(status_code=500, detail="批次号生成失败，请重试")
    for tpl_item in tpl.items:
        ei = ExecutionItem(
            execution_id=execution.id,
            template_item_id=tpl_item.id,
            score=0.0,
            max_score=tpl_item.score_weight,
            result="pending",
        )
        db.add(ei)
    _log(db, data.executor, "create_execution", "execution", execution.id, f"batch_no={batch_no}")
    db.commit()
    db.refresh(execution)
    return execution


@router.get("", response_model=list[ExecutionOut])
def list_executions(
    product_line_id: int | None = None,
    status: str | None = None,
    executor: str | None = None,
    batch_no: str | None = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(Execution)
    if product_line_id:
        q = q.filter(Execution.product_line_id == product_line_id)
    if status:
        q = q.filter(Execution.status == status)
    if executor:
        q = q.filter(Execution.executor == executor)
    if batch_no:
        q = q.filter(Execution.batch_no.contains(batch_no))
    return q.order_by(Execution.created_at.desc()).offset(skip).limit(limit).all()


@router.post("/nonconformances", response_model=NonConformanceOut)
def create_nonconformance(data: NonConformanceCreate, db: Session = Depends(get_db)):
    ei = db.query(ExecutionItem).filter(ExecutionItem.id == data.execution_item_id).first()
    if not ei:
        raise HTTPException(status_code=404, detail="执行检查项不存在")
    if ei.result != "fail":
        raise HTTPException(status_code=400, detail="只有不合格的检查项才能记录不符合")
    if data.severity not in SEVERITY_LADDER:
        raise HTTPException(status_code=400, detail=f"无效严重度，可选: {SEVERITY_LADDER}")
    level = SEVERITY_LADDER.index(data.severity) + 1
    nc = NonConformance(
        execution_item_id=data.execution_item_id,
        description=data.description,
        severity=data.severity,
        disposition=data.disposition,
        escalation_level=level,
        created_by=data.created_by,
    )
    db.add(nc)
    _log(db, data.created_by, "create_nc", "nonconformance", 0, data.description[:100])
    db.commit()
    db.refresh(nc)
    return nc


@router.post("/nonconformances/{nc_id}/escalate", response_model=NonConformanceOut)
def escalate_nonconformance(nc_id: int, data: NonConformanceEscalate, db: Session = Depends(get_db)):
    nc = db.query(NonConformance).filter(NonConformance.id == nc_id).first()
    if not nc:
        raise HTTPException(status_code=404, detail="不符合记录不存在")
    current_idx = SEVERITY_LADDER.index(nc.severity) if nc.severity in SEVERITY_LADDER else 0
    if current_idx >= len(SEVERITY_LADDER) - 1:
        raise HTTPException(status_code=400, detail="已达到最高严重度，无法继续升级")
    new_severity = SEVERITY_LADDER[current_idx + 1]
    new_nc = NonConformance(
        execution_item_id=nc.execution_item_id,
        description=f"[升级自NC#{nc.id}] {data.reason}" if data.reason else f"[升级自NC#{nc.id}]",
        severity=new_severity,
        disposition=nc.disposition,
        escalation_level=current_idx + 2,
        escalated_from_id=nc.id,
        escalated_at=datetime.utcnow(),
        created_by=data.escalated_by,
    )
    db.add(new_nc)
    _log(db, data.escalated_by, "escalate_nc", "nonconformance", nc_id, f"{nc.severity}->{new_severity}")
    db.commit()
    db.refresh(new_nc)
    return new_nc


@router.get("/nonconformances", response_model=list[NonConformanceOut])
def list_nonconformances(
    execution_id: int | None = None,
    severity: str | None = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(NonConformance)
    if execution_id:
        q = q.join(ExecutionItem).filter(ExecutionItem.execution_id == execution_id)
    if severity:
        q = q.filter(NonConformance.severity == severity)
    return q.order_by(NonConformance.created_at.desc()).offset(skip).limit(limit).all()


@router.post("/nonconformances/auto-escalate", response_model=list[NonConformanceOut])
def auto_escalate_overdue(db: Session = Depends(get_db)):
    from app.models import Rectification
    now = datetime.utcnow()
    overdue_rects = (
        db.query(Rectification)
        .filter(Rectification.due_date < now, Rectification.status.in_(["pending", "in_progress"]))
        .all()
    )
    escalated = []
    for rect in overdue_rects:
        nc = rect.nonconformance
        if not nc:
            continue
        current_idx = SEVERITY_LADDER.index(nc.severity) if nc.severity in SEVERITY_LADDER else -1
        if current_idx >= len(SEVERITY_LADDER) - 1:
            continue
        new_severity = SEVERITY_LADDER[current_idx + 1]
        new_nc = NonConformance(
            execution_item_id=nc.execution_item_id,
            description=f"[超期自动升级自NC#{nc.id}] 整改单#{rect.id}已逾期",
            severity=new_severity,
            disposition=nc.disposition,
            escalation_level=current_idx + 2,
            escalated_from_id=nc.id,
            escalated_at=now,
            created_by="system",
        )
        db.add(new_nc)
        escalated.append(new_nc)
    db.commit()
    for nc in escalated:
        db.refresh(nc)
    return escalated


@router.get("/{execution_id}", response_model=ExecutionOut)
def get_execution(execution_id: int, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return execution


@router.post("/{execution_id}/score", response_model=ExecutionOut)
def batch_score(execution_id: int, data: BatchScoreRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status != "in_progress":
        raise HTTPException(status_code=400, detail="只有进行中的执行记录才能打分")
    now = datetime.utcnow()
    for item_score in data.items:
        ei = (
            db.query(ExecutionItem)
            .filter(
                ExecutionItem.execution_id == execution_id,
                ExecutionItem.template_item_id == item_score.template_item_id,
            )
            .first()
        )
        if not ei:
            raise HTTPException(
                status_code=400,
                detail=f"检查项 template_item_id={item_score.template_item_id} 不属于该执行记录",
            )
        if ei.result not in ("pending", "") and ei.scored_by:
            rev = ScoreRevision(
                execution_item_id=ei.id,
                old_score=ei.score, new_score=item_score.score,
                old_result=ei.result, new_result=item_score.result,
                old_remark=ei.remark or "", new_remark=item_score.remark,
                old_max_score=ei.max_score, new_max_score=item_score.max_score,
                changed_by=item_score.scored_by, reason="首次打分覆盖",
            )
            db.add(rev)
        ei.score = item_score.score
        ei.max_score = item_score.max_score
        ei.result = item_score.result
        ei.remark = item_score.remark
        ei.scored_by = item_score.scored_by
        ei.scored_at = now
    all_items = db.query(ExecutionItem).filter(ExecutionItem.execution_id == execution_id).all()
    execution.total_score = sum(i.score for i in all_items)
    execution.max_score = sum(i.max_score for i in all_items)
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/score-modify", response_model=ExecutionOut)
def modify_scores(execution_id: int, data: ScoreModifyRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status not in ("completed", "arbitrated"):
        raise HTTPException(status_code=400, detail="只有已完成或已仲裁的执行记录才能修改打分")
    now = datetime.utcnow()
    for item_score in data.items:
        ei = (
            db.query(ExecutionItem)
            .filter(
                ExecutionItem.execution_id == execution_id,
                ExecutionItem.template_item_id == item_score.template_item_id,
            )
            .first()
        )
        if not ei:
            raise HTTPException(
                status_code=400,
                detail=f"检查项 template_item_id={item_score.template_item_id} 不属于该执行记录",
            )
        if ei.result == "pending":
            raise HTTPException(status_code=400, detail="未打分的检查项请用打分接口，不能用修改接口")
        rev = ScoreRevision(
            execution_item_id=ei.id,
            old_score=ei.score, new_score=item_score.score,
            old_result=ei.result, new_result=item_score.result,
            old_remark=ei.remark or "", new_remark=item_score.remark,
            old_max_score=ei.max_score, new_max_score=item_score.max_score,
            changed_by=data.changed_by, reason=data.reason,
        )
        db.add(rev)
        ei.score = item_score.score
        ei.max_score = item_score.max_score
        ei.result = item_score.result
        ei.remark = item_score.remark
        ei.scored_by = item_score.scored_by
        ei.scored_at = now
    all_items = db.query(ExecutionItem).filter(ExecutionItem.execution_id == execution_id).all()
    execution.total_score = sum(i.score for i in all_items)
    execution.max_score = sum(i.max_score for i in all_items)
    _log(db, data.changed_by, "modify_scores", "execution", execution_id, data.reason)
    db.commit()
    db.refresh(execution)
    return execution


@router.get("/{execution_id}/score-revisions", response_model=list[ScoreRevisionOut])
def list_score_revisions(execution_id: int, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    ei_ids = [ei.id for ei in execution.execution_items]
    if not ei_ids:
        return []
    return db.query(ScoreRevision).filter(ScoreRevision.execution_item_id.in_(ei_ids)).order_by(ScoreRevision.changed_at.desc()).all()


@router.post("/{execution_id}/complete", response_model=ExecutionOut)
def complete_execution(execution_id: int, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status != "in_progress":
        raise HTTPException(status_code=400, detail="只有进行中的执行记录才能完成")
    pending = (
        db.query(ExecutionItem)
        .filter(ExecutionItem.execution_id == execution_id, ExecutionItem.result == "pending")
        .count()
    )
    if pending > 0:
        raise HTTPException(status_code=400, detail=f"还有 {pending} 项未打分，无法完成")
    execution.status = "completed"
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/force-complete", response_model=ExecutionOut)
def force_complete_execution(execution_id: int, data: ForceCompleteRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status != "in_progress":
        raise HTTPException(status_code=400, detail="只有进行中的执行记录才能强制完成")
    execution.status = "completed"
    execution.force_completed = 1
    _log(db, data.operated_by, "force_complete", "execution", execution_id, data.reason)
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/reopen", response_model=ExecutionOut)
def reopen_execution(execution_id: int, data: ReopenRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status not in ("completed", "cancelled", "arbitrated"):
        raise HTTPException(status_code=400, detail="当前状态不允许重新打开")
    execution.status = "in_progress"
    execution.arbitration_result = None
    execution.arbitration_by = ""
    execution.arbitration_at = None
    execution.arbitration_comment = ""
    execution.force_completed = 0
    _log(db, data.operated_by, "reopen_execution", "execution", execution_id, data.reason)
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/cancel", response_model=ExecutionOut)
def cancel_execution(execution_id: int, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status not in ("in_progress", "completed"):
        raise HTTPException(status_code=400, detail="当前状态不允许取消")
    execution.status = "cancelled"
    db.commit()
    db.refresh(execution)
    return execution
