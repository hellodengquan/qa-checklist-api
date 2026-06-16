import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    Execution, ExecutionItem, ChecklistTemplate, TemplateItem,
    NonConformance, ScoreRevision, AuditLog, generate_batch_no,
    NCEscalationRule, ReplayLock, DeadLetterArchive, NCThresholdTuning,
)
from app.schemas import (
    ExecutionCreate, ExecutionOut, ExecutionItemScore,
    BatchScoreRequest, NonConformanceCreate, NonConformanceOut,
    NonConformanceEscalate, ScoreModifyRequest, ScoreRevisionOut,
    ForceCompleteRequest, ReopenRequest, SuspendRequest, TerminateRequest,
    ScoreReplayRequest, NCEscalationRuleCreate, NCEscalationRuleOut,
    ScoreReplayConcurrencyRequest, ScoreReplayConcurrencyOut,
    DeadLetterArchiveRequest, DeadLetterArchiveOut,
    NCThresholdTuningRequest, NCThresholdTuningOut,
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


@router.post("/escalation-rules", response_model=NCEscalationRuleOut)
def create_escalation_rule(data: NCEscalationRuleCreate, db: Session = Depends(get_db)):
    if data.from_severity not in SEVERITY_LADDER:
        raise HTTPException(status_code=400, detail=f"from_severity 无效，可选: {SEVERITY_LADDER}")
    if data.to_severity not in SEVERITY_LADDER:
        raise HTTPException(status_code=400, detail=f"to_severity 无效，可选: {SEVERITY_LADDER}")
    if SEVERITY_LADDER.index(data.to_severity) <= SEVERITY_LADDER.index(data.from_severity):
        raise HTTPException(status_code=400, detail="to_severity 必须比 from_severity 更严重")
    rule = NCEscalationRule(
        product_line_id=data.product_line_id,
        trigger_type=data.trigger_type,
        trigger_value=data.trigger_value,
        from_severity=data.from_severity,
        to_severity=data.to_severity,
        window_days=data.window_days,
        rule_name=data.rule_name or f"{data.from_severity}->{data.to_severity}",
        created_by=data.created_by,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/escalation-rules", response_model=list[NCEscalationRuleOut])
def list_escalation_rules(
    product_line_id: int | None = None,
    is_active: int | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(NCEscalationRule)
    if product_line_id is not None:
        q = q.filter(NCEscalationRule.product_line_id == product_line_id)
    if is_active is not None:
        q = q.filter(NCEscalationRule.is_active == is_active)
    return q.order_by(NCEscalationRule.created_at.desc()).all()


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
    _auto_check_escalation_rules(db, nc)
    db.refresh(nc)
    return nc


def _auto_check_escalation_rules(db: Session, new_nc: NonConformance):
    ei = db.query(ExecutionItem).filter(ExecutionItem.id == new_nc.execution_item_id).first()
    if not ei:
        return
    execution = db.query(Execution).filter(Execution.id == ei.execution_id).first()
    if not execution:
        return
    rules = db.query(NCEscalationRule).filter(
        NCEscalationRule.is_active == 1,
        (NCEscalationRule.product_line_id == None) | (
            NCEscalationRule.product_line_id == execution.product_line_id),
        NCEscalationRule.from_severity == new_nc.severity,
    ).all()
    if not rules:
        return
    now = datetime.utcnow()
    tpl_item = db.query(TemplateItem).filter(TemplateItem.id == ei.template_item_id).first()
    item_name = tpl_item.name if tpl_item else ""
    for rule in rules:
        if rule.trigger_type == "recurring_count":
            window_start = now - timedelta(days=rule.window_days)
            same_item_nc_count = (
                db.query(NonConformance)
                .join(ExecutionItem, NonConformance.execution_item_id == ExecutionItem.id)
                .join(Execution, ExecutionItem.execution_id == Execution.id)
                .filter(
                    ExecutionItem.template_item_id == ei.template_item_id,
                    Execution.product_line_id == execution.product_line_id,
                    NonConformance.severity == new_nc.severity,
                    NonConformance.created_at >= window_start,
                )
                .count()
            )
            if same_item_nc_count >= rule.trigger_value:
                _do_auto_escalate(db, new_nc, rule, "system",
                                  f"[{rule.rule_name}] 规则触发，同项累计 {same_item_nc_count} 次")
                break


def _do_auto_escalate(db: Session, nc: NonConformance, rule: NCEscalationRule, created_by: str, reason: str):
    current_idx = SEVERITY_LADDER.index(nc.severity) if nc.severity in SEVERITY_LADDER else -1
    if current_idx >= len(SEVERITY_LADDER) - 1:
        return None
    new_severity = rule.to_severity
    now = datetime.utcnow()
    new_nc = NonConformance(
        execution_item_id=nc.execution_item_id,
        description=f"[规则自动升级自NC#{nc.id}] {reason}",
        severity=new_severity,
        disposition=nc.disposition,
        escalation_level=current_idx + 2,
        escalated_from_id=nc.id,
        escalated_at=now,
        created_by=created_by,
    )
    db.add(new_nc)
    db.flush()
    _log(db, created_by, "auto_escalate_nc", "nonconformance", nc.id, f"{nc.severity}->{new_severity}")
    db.commit()
    db.refresh(new_nc)
    return new_nc


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


# ============ executions 异常流转死信清理（放 /{execution_id} 之前避免路由冲突）============

@router.post("/dead-letter/archive", response_model=list[DeadLetterArchiveOut])
def archive_dead_letter_executions(data: DeadLetterArchiveRequest, db: Session = Depends(get_db)):
    q = db.query(Execution).filter(Execution.status.in_(["cancelled", "terminated"]))
    if data.execution_ids:
        q = q.filter(Execution.id.in_(data.execution_ids))
    execs = q.all()
    archived = []
    now = datetime.utcnow()
    for ex in execs:
        if ex.dead_letter_flag:
            continue
        snapshot = {
            "id": ex.id, "batch_no": ex.batch_no, "status": ex.status,
            "executor": ex.executor, "total_score": ex.total_score,
            "max_score": ex.max_score, "created_at": ex.created_at.isoformat() if ex.created_at else None,
            "terminate_reason": ex.terminate_reason, "suspend_reason": ex.suspend_reason,
        }
        archive = DeadLetterArchive(
            execution_id=ex.id,
            batch_no=ex.batch_no,
            original_status=ex.status,
            dead_letter_reason=data.reason or f"状态={ex.status} 归档清理",
            archived_by="system",
            snapshot=snapshot,
            archived_at=now,
        )
        db.add(archive)
        ex.dead_letter_flag = 1
        ex.dead_letter_reason = data.reason
        ex.dead_letter_at = now
        ex.archive_snapshot = snapshot
        archived.append(archive)
    db.commit()
    for a in archived:
        db.refresh(a)
    return archived


@router.get("/dead-letter/list", response_model=list[DeadLetterArchiveOut])
def list_dead_letter_archives(limit: int = 200, db: Session = Depends(get_db)):
    return db.query(DeadLetterArchive).order_by(DeadLetterArchive.archived_at.desc()).limit(limit).all()


# ============ NC 升级阈值动态调优（放 /{execution_id} 之前避免路由冲突）============

@router.post("/nc-threshold/analyze", response_model=NCThresholdTuningOut)
def analyze_nc_threshold(data: NCThresholdTuningRequest, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    start = now - timedelta(days=data.window_days)
    q = db.query(NonConformance).filter(NonConformance.created_at >= start)
    if data.product_line_id:
        q = q.join(ExecutionItem, ExecutionItem.id == NonConformance.execution_item_id) \
             .join(Execution, Execution.id == ExecutionItem.execution_id) \
             .filter(Execution.product_line_id == data.product_line_id)
    q = q.filter(NonConformance.severity == data.severity)
    samples = q.all()
    sample_size = len(samples)
    current_rules = db.query(NCEscalationRule).all()
    current_rule = None
    for r in current_rules:
        if r.from_severity == data.severity and r.trigger_type == data.trigger_type:
            current_rule = r
            break
    if not current_rule:
        current_value = 0.0
    else:
        current_value = float(current_rule.trigger_value)
    if sample_size < 5:
        recommended_value = current_value or 3.0
        confidence = 0.3
    else:
        if data.trigger_type == "recurring_count":
            user_map: dict = {}
            for s in samples:
                k = s.created_by
                user_map[k] = user_map.get(k, 0) + 1
            counts = list(user_map.values())
            if counts:
                avg = sum(counts) / len(counts)
                recommended_value = round(max(2.0, avg * 1.5), 1)
                confidence = min(0.95, 0.4 + sample_size * 0.02)
            else:
                recommended_value = 3.0
                confidence = 0.3
        elif data.trigger_type == "overdue_days":
            recommended_value = 5.0
            confidence = 0.6
        else:
            recommended_value = current_value or 3.0
            confidence = 0.5
    detail = {
        "sample_size": sample_size,
        "current_rule_id": current_rule.id if current_rule else None,
        "severity": data.severity,
        "trigger_type": data.trigger_type,
    }
    tuning = NCThresholdTuning(
        product_line_id=data.product_line_id,
        severity=data.severity,
        trigger_type=data.trigger_type,
        current_value=current_value,
        recommended_value=recommended_value,
        confidence=confidence,
        sample_size=sample_size,
        analysis_window_days=data.window_days,
        analyzed_by="system",
        analyzed_at=now,
        detail=detail,
    )
    db.add(tuning)
    if data.apply_recommendation and current_rule:
        current_rule.trigger_value = int(round(recommended_value))
        detail["applied"] = True
    db.commit()
    db.refresh(tuning)
    return tuning


@router.get("/nc-threshold/history", response_model=list[NCThresholdTuningOut])
def list_nc_threshold_history(limit: int = 100, db: Session = Depends(get_db)):
    return db.query(NCThresholdTuning).order_by(NCThresholdTuning.analyzed_at.desc()).limit(limit).all()


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
    group_id = uuid.uuid4().hex[:12]
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
                execution_id=execution_id,
                old_score=ei.score, new_score=item_score.score,
                old_result=ei.result, new_result=item_score.result,
                old_remark=ei.remark or "", new_remark=item_score.remark,
                old_max_score=ei.max_score, new_max_score=item_score.max_score,
                changed_by=item_score.scored_by, reason="首次打分覆盖",
                revision_group=group_id,
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
    if execution.status not in ("completed", "arbitrated", "in_progress"):
        raise HTTPException(status_code=400, detail="当前状态不允许修改打分")
    now = datetime.utcnow()
    group_id = uuid.uuid4().hex[:12]
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
            execution_id=execution_id,
            old_score=ei.score, new_score=item_score.score,
            old_result=ei.result, new_result=item_score.result,
            old_remark=ei.remark or "", new_remark=item_score.remark,
            old_max_score=ei.max_score, new_max_score=item_score.max_score,
            changed_by=data.changed_by, reason=data.reason,
            revision_group=group_id,
            snapshot={
                "score": ei.score, "result": ei.result, "remark": ei.remark,
                "max_score": ei.max_score, "scored_by": ei.scored_by,
            },
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
    db.flush()
    last_rev = (
        db.query(ScoreRevision).filter(ScoreRevision.execution_id == execution_id)
        .order_by(ScoreRevision.changed_at.desc()).first()
    )
    if last_rev:
        execution.last_revision_id = last_rev.id
    _log(db, data.changed_by, "modify_scores", "execution", execution_id, data.reason)
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/score-replay", response_model=ExecutionOut)
def replay_score_revisions(execution_id: int, data: ScoreReplayRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status == "terminated":
        raise HTTPException(status_code=400, detail="已终止的执行记录不能回放")
    if data.revision_ids:
        revisions = (
            db.query(ScoreRevision)
            .filter(
                ScoreRevision.id.in_(data.revision_ids),
                ScoreRevision.execution_id == execution_id,
            )
            .order_by(ScoreRevision.changed_at.asc())
            .all()
        )
    elif data.revision_group:
        revisions = (
            db.query(ScoreRevision)
            .filter(
                ScoreRevision.revision_group == data.revision_group,
                ScoreRevision.execution_id == execution_id,
            )
            .order_by(ScoreRevision.changed_at.asc())
            .all()
        )
    else:
        raise HTTPException(status_code=400, detail="必须指定 revision_ids 或 revision_group")
    if not revisions:
        raise HTTPException(status_code=404, detail="未找到匹配的修订记录")
    now = datetime.utcnow()
    group_id = uuid.uuid4().hex[:12]
    for rev in revisions:
        ei = db.query(ExecutionItem).filter(ExecutionItem.id == rev.execution_item_id).first()
        if not ei:
            continue
        if ei.execution_id != execution_id:
            continue
        rollback_rev = ScoreRevision(
            execution_item_id=ei.id,
            execution_id=execution_id,
            old_score=ei.score, new_score=rev.old_score,
            old_result=ei.result, new_result=rev.old_result,
            old_remark=ei.remark or "", new_remark=rev.old_remark,
            old_max_score=ei.max_score, new_max_score=rev.old_max_score,
            changed_by=data.operated_by,
            reason=f"[回放REV#{rev.id}] {data.reason}",
            revision_group=group_id,
            snapshot={
                "replayed_revision_id": rev.id,
                "original_changed_by": rev.changed_by,
                "original_reason": rev.reason,
            },
        )
        db.add(rollback_rev)
        ei.score = rev.old_score
        ei.max_score = rev.old_max_score
        ei.result = rev.old_result
        ei.remark = rev.old_remark
        ei.scored_by = rev.changed_by
        ei.scored_at = now
    all_items = db.query(ExecutionItem).filter(ExecutionItem.execution_id == execution_id).all()
    execution.total_score = sum(i.score for i in all_items)
    execution.max_score = sum(i.max_score for i in all_items)
    _log(db, data.operated_by, "replay_scores", "execution", execution_id,
         f"revs={[r.id for r in revisions]}")
    db.commit()
    db.refresh(execution)
    return execution


@router.get("/{execution_id}/score-revisions", response_model=list[ScoreRevisionOut])
def list_score_revisions(execution_id: int, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return (
        db.query(ScoreRevision)
        .filter(ScoreRevision.execution_id == execution_id)
        .order_by(ScoreRevision.changed_at.desc())
        .all()
    )


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


@router.post("/{execution_id}/suspend", response_model=ExecutionOut)
def suspend_execution(execution_id: int, data: SuspendRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status != "in_progress":
        raise HTTPException(status_code=400, detail="只有进行中的执行记录才能暂停")
    execution.status = "suspended"
    execution.suspended_by = data.operated_by
    execution.suspended_at = datetime.utcnow()
    execution.suspend_reason = data.reason
    _log(db, data.operated_by, "suspend_execution", "execution", execution_id, data.reason)
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/resume", response_model=ExecutionOut)
def resume_execution(execution_id: int, operated_by: str = "", reason: str = "", db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status != "suspended":
        raise HTTPException(status_code=400, detail="只有暂停状态的执行记录才能恢复")
    execution.status = "in_progress"
    execution.suspended_by = ""
    execution.suspended_at = None
    execution.suspend_reason = ""
    _log(db, operated_by, "resume_execution", "execution", execution_id, reason)
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/terminate", response_model=ExecutionOut)
def terminate_execution(execution_id: int, data: TerminateRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status in ("terminated", "cancelled"):
        raise HTTPException(status_code=400, detail="当前状态不允许终止")
    execution.status = "terminated"
    execution.terminated_by = data.operated_by
    execution.terminated_at = datetime.utcnow()
    execution.terminate_reason = data.reason
    _log(db, data.operated_by, "terminate_execution", "execution", execution_id, data.reason)
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/reopen", response_model=ExecutionOut)
def reopen_execution(execution_id: int, data: ReopenRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status not in ("completed", "cancelled", "arbitrated", "suspended", "terminated"):
        raise HTTPException(status_code=400, detail="当前状态不允许重新打开")
    execution.status = "in_progress"
    execution.arbitration_result = None
    execution.arbitration_by = ""
    execution.arbitration_at = None
    execution.arbitration_comment = ""
    execution.force_completed = 0
    execution.suspended_by = ""
    execution.suspended_at = None
    execution.suspend_reason = ""
    execution.terminated_by = ""
    execution.terminated_at = None
    execution.terminate_reason = ""
    _log(db, data.operated_by, "reopen_execution", "execution", execution_id, data.reason)
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/cancel", response_model=ExecutionOut)
def cancel_execution(execution_id: int, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status not in ("in_progress", "completed", "suspended"):
        raise HTTPException(status_code=400, detail="当前状态不允许取消")
    execution.status = "cancelled"
    db.commit()
    db.refresh(execution)
    return execution


# ============ ScoreRevision 回放并发隔离 ============

@router.post("/{execution_id}/replay-lock", response_model=ScoreReplayConcurrencyOut)
def acquire_replay_lock(execution_id: int, data: ScoreReplayConcurrencyRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    active_locks = db.query(ReplayLock).filter(
        ReplayLock.execution_id == execution_id,
        ReplayLock.status == "active",
    ).all()
    now = datetime.utcnow()
    for lk in active_locks:
        if lk.expires_at and lk.expires_at < now:
            lk.status = "expired"
        else:
            raise HTTPException(status_code=409, detail=f"执行记录存在活跃回放锁 token={lk.replay_token}")
    token = f"RP-{uuid.uuid4().hex[:16]}"
    lock = ReplayLock(
        execution_id=execution_id,
        replay_token=token,
        revision_ids=",".join(str(x) for x in data.revision_ids),
        revision_group=data.revision_group,
        held_by=data.held_by,
        held_at=now,
        expires_at=now + timedelta(seconds=data.ttl_seconds),
        status="active",
    )
    db.add(lock)
    db.flush()
    if data.revision_ids:
        for rev_id in data.revision_ids:
            rev = db.query(ScoreRevision).filter(ScoreRevision.id == rev_id).first()
            if rev:
                rev.replay_token = token
                rev.replay_status = "locked"
                rev.version_stamp = (rev.version_stamp or 0) + 1
    _log(db, data.held_by, "acquire_replay_lock", "execution", execution_id, token)
    db.commit()
    db.refresh(lock)
    return lock


@router.post("/{execution_id}/replay-lock/{replay_token}/release", response_model=ScoreReplayConcurrencyOut)
def release_replay_lock(execution_id: int, replay_token: str, db: Session = Depends(get_db)):
    lock = db.query(ReplayLock).filter(
        ReplayLock.execution_id == execution_id,
        ReplayLock.replay_token == replay_token,
    ).first()
    if not lock:
        raise HTTPException(status_code=404, detail="回放锁不存在")
    lock.status = "released"
    revs = db.query(ScoreRevision).filter(ScoreRevision.replay_token == replay_token).all()
    for rev in revs:
        rev.replay_status = "unlocked"
    db.commit()
    db.refresh(lock)
    return lock
