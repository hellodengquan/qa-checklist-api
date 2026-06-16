from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import ChecklistTemplate, TemplateItem, Execution, ExecutionItem, AuditLog, MigrationBatch
from app.schemas import (
    TemplateCreate, TemplateOut, TemplateItemCreate, TemplateItemOut,
    TemplateVersionOut, TemplateMigrateRequest, TemplateRollbackRequest,
    TemplateCostEstimateOut,
    MigrationBatchCreate, MigrationBatchOut,
)

router = APIRouter(prefix="/api/templates", tags=["清单模板管理"])


def _log(db: Session, username: str, action: str, rtype: str, rid: int, detail: str = ""):
    db.add(AuditLog(username=username, action=action, resource_type=rtype, resource_id=rid, detail=detail))


@router.post("", response_model=TemplateOut)
def create_template(data: TemplateCreate, db: Session = Depends(get_db)):
    pl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == data.product_line_id).first()
    if not pl:
        from app.models import ProductLine
        pl_exists = db.query(ProductLine).filter(ProductLine.id == data.product_line_id).first()
        if not pl_exists:
            raise HTTPException(status_code=400, detail="产品线不存在")
    existing = (
        db.query(ChecklistTemplate)
        .filter(ChecklistTemplate.product_line_id == data.product_line_id, ChecklistTemplate.name == data.name)
        .order_by(ChecklistTemplate.version.desc())
        .first()
    )
    version = (existing.version + 1) if existing else 1
    tpl = ChecklistTemplate(
        product_line_id=data.product_line_id,
        name=data.name,
        version=version,
        description=data.description,
        status="draft",
        created_by=data.created_by,
    )
    db.add(tpl)
    db.flush()
    for idx, item_data in enumerate(data.items):
        item = TemplateItem(
            template_id=tpl.id,
            category=item_data.category,
            name=item_data.name,
            description=item_data.description,
            standard=item_data.standard,
            sort_order=item_data.sort_order or idx,
            is_required=item_data.is_required,
            score_weight=item_data.score_weight,
        )
        db.add(item)
    _log(db, data.created_by, "create_template", "template", tpl.id, f"v{version}")
    db.commit()
    db.refresh(tpl)
    return tpl


@router.get("", response_model=list[TemplateOut])
def list_templates(
    product_line_id: int | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(ChecklistTemplate)
    if product_line_id:
        q = q.filter(ChecklistTemplate.product_line_id == product_line_id)
    if status:
        q = q.filter(ChecklistTemplate.status == status)
    return q.order_by(ChecklistTemplate.created_at.desc()).offset(skip).limit(limit).all()


# ============ 版本迁移/回滚分批策略（放 /{template_id} 之前避免路由冲突）============

@router.post("/migration-batches", response_model=MigrationBatchOut)
def create_migration_batch(data: MigrationBatchCreate, created_by: str = "system", db: Session = Depends(get_db)):
    from_tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == data.from_template_id).first()
    to_tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == data.to_template_id).first()
    if not from_tpl or not to_tpl:
        raise HTTPException(status_code=404, detail="源模板或目标模板不存在")
    q = db.query(Execution).filter(Execution.template_id == data.from_template_id)
    if data.strategy == "time_window":
        if data.time_window_start:
            try:
                t_start = datetime.strptime(data.time_window_start, "%Y-%m-%d")
                q = q.filter(Execution.created_at >= t_start)
            except ValueError:
                pass
        if data.time_window_end:
            try:
                t_end = datetime.strptime(data.time_window_end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
                q = q.filter(Execution.created_at <= t_end)
            except ValueError:
                pass
    total = q.count()
    tw_start = None
    tw_end = None
    if data.time_window_start:
        try:
            tw_start = datetime.strptime(data.time_window_start, "%Y-%m-%d")
        except ValueError:
            pass
    if data.time_window_end:
        try:
            tw_end = datetime.strptime(data.time_window_end, "%Y-%m-%d")
        except ValueError:
            pass
    batch = MigrationBatch(
        from_template_id=data.from_template_id,
        to_template_id=data.to_template_id,
        strategy=data.strategy,
        batch_size=data.batch_size,
        time_window_start=tw_start,
        time_window_end=tw_end,
        total_target=total,
        total_processed=0,
        total_failed=0,
        status="pending",
        created_by=created_by,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


@router.post("/migration-batches/{batch_id}/run-next", response_model=MigrationBatchOut)
def run_migration_batch_next(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(MigrationBatch).filter(MigrationBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="分批任务不存在")
    if batch.status == "completed":
        raise HTTPException(status_code=400, detail="分批任务已完成")
    batch.status = "running"
    q = db.query(Execution).filter(Execution.template_id == batch.from_template_id)
    if batch.strategy == "time_window":
        if batch.time_window_start:
            q = q.filter(Execution.created_at >= batch.time_window_start)
        if batch.time_window_end:
            q = q.filter(Execution.created_at <= batch.time_window_end)
    q = q.filter(Execution.status != "cancelled")
    remaining = q.offset(batch.total_processed).limit(batch.batch_size).all()
    processed = 0
    failed = 0
    for exec_obj in remaining:
        try:
            exec_obj.template_id = batch.to_template_id
            processed += 1
        except Exception:
            failed += 1
    batch.total_processed += processed
    batch.total_failed += failed
    if batch.total_processed + batch.total_failed >= batch.total_target:
        batch.status = "completed"
    else:
        batch.status = "paused"
    db.commit()
    db.refresh(batch)
    return batch


@router.get("/migration-batches", response_model=list[MigrationBatchOut])
def list_migration_batches(status: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(MigrationBatch)
    if status:
        q = q.filter(MigrationBatch.status == status)
    return q.order_by(MigrationBatch.created_at.desc()).limit(limit).all()


@router.get("/migration-batches/{batch_id}", response_model=MigrationBatchOut)
def get_migration_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.query(MigrationBatch).filter(MigrationBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="分批任务不存在")
    return batch


@router.get("/{template_id}", response_model=TemplateOut)
def get_template(template_id: int, db: Session = Depends(get_db)):
    tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    return tpl


@router.put("/{template_id}/status", response_model=TemplateOut)
def update_template_status(template_id: int, status: str, db: Session = Depends(get_db)):
    if status not in ("draft", "active", "archived"):
        raise HTTPException(status_code=400, detail="无效状态，可选: draft/active/archived")
    tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    if status == "active":
        existing_active = (
            db.query(ChecklistTemplate)
            .filter(
                ChecklistTemplate.product_line_id == tpl.product_line_id,
                ChecklistTemplate.name == tpl.name,
                ChecklistTemplate.status == "active",
                ChecklistTemplate.id != tpl.id,
            )
            .first()
        )
        if existing_active:
            raise HTTPException(status_code=400, detail=f"同产品线下已有激活版本(模板#{existing_active.id} v{existing_active.version})，请先归档旧版本")
    tpl.status = status
    db.commit()
    db.refresh(tpl)
    return tpl


@router.get("/{template_id}/versions", response_model=list[TemplateVersionOut])
def list_template_versions(template_id: int, db: Session = Depends(get_db)):
    tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    return (
        db.query(ChecklistTemplate)
        .filter(
            ChecklistTemplate.product_line_id == tpl.product_line_id,
            ChecklistTemplate.name == tpl.name,
        )
        .order_by(ChecklistTemplate.version.asc())
        .all()
    )


def _compute_item_diff(old_tpl: ChecklistTemplate, new_tpl: ChecklistTemplate):
    old_map = {(it.category, it.name): it for it in old_tpl.items}
    new_map = {(it.category, it.name): it for it in new_tpl.items}
    added, removed, modified = 0, 0, 0
    for key, new_item in new_map.items():
        if key not in old_map:
            added += 1
            continue
        old_item = old_map[key]
        if (old_item.description != new_item.description
                or old_item.standard != new_item.standard
                or old_item.score_weight != new_item.score_weight
                or old_item.is_required != new_item.is_required):
            modified += 1
    for key in old_map:
        if key not in new_map:
            removed += 1
    return added, removed, modified


def _estimate_cost(
    db: Session, tpl: ChecklistTemplate, from_tpl: ChecklistTemplate, to_tpl: ChecklistTemplate,
) -> TemplateCostEstimateOut:
    in_progress_count = (
        db.query(Execution).filter(
            Execution.template_id == from_tpl.id, Execution.status == "in_progress",
        ).count()
    )
    completed_count = (
        db.query(Execution).filter(
            Execution.template_id == from_tpl.id,
            Execution.status.in_(["completed", "arbitrated"]),
        ).count()
    )
    added, removed, modified = _compute_item_diff(from_tpl, to_tpl)
    total_items = max(len(from_tpl.items), 1)
    change_ratio = (added + removed + modified) / total_items
    complexity = int(
        in_progress_count * 5
        + completed_count * 2
        + added * 3
        + removed * 4
        + modified * 2
        + change_ratio * 10
    )
    if complexity >= 40 or (in_progress_count >= 5 and change_ratio >= 0.5):
        risk = "high"
        recommendation = "建议先评估执行记录影响，考虑分批迁移或强制在空闲时段迁移"
    elif complexity >= 15 or (in_progress_count >= 2 and change_ratio >= 0.3):
        risk = "medium"
        recommendation = "建议确认检查项差异和进行中执行数量后再迁移"
    else:
        risk = "low"
        recommendation = "可以安全迁移"
    return TemplateCostEstimateOut(
        template_id=tpl.id,
        template_name=tpl.name,
        from_version=from_tpl.version,
        to_version=to_tpl.version,
        affected_in_progress=in_progress_count,
        affected_completed=completed_count,
        affected_total=in_progress_count + completed_count,
        item_diff_added=added,
        item_diff_removed=removed,
        item_diff_modified=modified,
        complexity_score=complexity,
        risk_level=risk,
        recommendation=recommendation,
    )


@router.get("/{template_id}/estimate-migrate", response_model=TemplateCostEstimateOut)
def estimate_migrate(template_id: int, db: Session = Depends(get_db)):
    new_tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == template_id).first()
    if not new_tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    old_tpl = (
        db.query(ChecklistTemplate)
        .filter(
            ChecklistTemplate.product_line_id == new_tpl.product_line_id,
            ChecklistTemplate.name == new_tpl.name,
            ChecklistTemplate.status == "active",
            ChecklistTemplate.id != new_tpl.id,
        )
        .first()
    )
    if not old_tpl:
        raise HTTPException(status_code=400, detail="没有找到当前激活的旧版本模板，无法评估迁移成本")
    return _estimate_cost(db, new_tpl, old_tpl, new_tpl)


@router.get("/{template_id}/estimate-rollback", response_model=TemplateCostEstimateOut)
def estimate_rollback(template_id: int, target_version: int, db: Session = Depends(get_db)):
    current_tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == template_id).first()
    if not current_tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    target_tpl = (
        db.query(ChecklistTemplate)
        .filter(
            ChecklistTemplate.product_line_id == current_tpl.product_line_id,
            ChecklistTemplate.name == current_tpl.name,
            ChecklistTemplate.version == target_version,
        )
        .first()
    )
    if not target_tpl:
        raise HTTPException(status_code=400, detail=f"目标版本 v{target_version} 不存在")
    active_tpl = (
        db.query(ChecklistTemplate)
        .filter(
            ChecklistTemplate.product_line_id == current_tpl.product_line_id,
            ChecklistTemplate.name == current_tpl.name,
            ChecklistTemplate.status == "active",
        )
        .first()
    )
    from_tpl = active_tpl or current_tpl
    return _estimate_cost(db, current_tpl, from_tpl, target_tpl)


@router.post("/{template_id}/migrate", response_model=dict)
def migrate_executions(template_id: int, data: TemplateMigrateRequest, db: Session = Depends(get_db)):
    new_tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == template_id).first()
    if not new_tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    if new_tpl.status not in ("draft", "active"):
        raise HTTPException(status_code=400, detail="只能从 draft 或 active 状态的模板执行迁移")
    old_tpls = (
        db.query(ChecklistTemplate)
        .filter(
            ChecklistTemplate.product_line_id == new_tpl.product_line_id,
            ChecklistTemplate.name == new_tpl.name,
            ChecklistTemplate.id != new_tpl.id,
            ChecklistTemplate.status == "active",
        )
        .all()
    )
    if not old_tpls and new_tpl.status == "draft":
        raise HTTPException(status_code=400, detail="没有找到旧版本激活模板，无法迁移")
    old_tpl = old_tpls[0] if old_tpls else None
    if old_tpl:
        old_tpl.status = "archived"
    new_tpl.status = "active"
    old_tpl_id = old_tpl.id if old_tpl else None
    old_tpl_version = old_tpl.version if old_tpl else None
    if old_tpl:
        in_progress_execs = (
            db.query(Execution)
            .filter(Execution.template_id == old_tpl.id, Execution.status == "in_progress")
            .all()
        )
    else:
        in_progress_execs = []
    migrated_count = 0
    for execution in in_progress_execs:
        old_items_map = {ei.template_item_id: ei for ei in execution.execution_items}
        execution.template_id = new_tpl.id
        execution.max_score = sum(item.score_weight for item in new_tpl.items)
        for new_tpl_item in new_tpl.items:
            if new_tpl_item.id not in old_items_map:
                ei = ExecutionItem(
                    execution_id=execution.id,
                    template_item_id=new_tpl_item.id,
                    score=0.0,
                    max_score=new_tpl_item.score_weight,
                    result="pending",
                )
                db.add(ei)
        execution.total_score = sum(i.score for i in execution.execution_items)
        migrated_count += 1
    _log(db, data.operated_by, "migrate_template", "template", template_id,
         f"v{old_tpl_version}->{new_tpl.version}, migrated={migrated_count}")
    db.commit()
    return {
        "detail": "迁移完成",
        "archived_template_id": old_tpl_id,
        "archived_version": old_tpl_version,
        "migrated_executions": migrated_count,
    }


@router.post("/{template_id}/rollback", response_model=dict)
def rollback_template(template_id: int, data: TemplateRollbackRequest, db: Session = Depends(get_db)):
    current_tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == template_id).first()
    if not current_tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    target_tpl = (
        db.query(ChecklistTemplate)
        .filter(
            ChecklistTemplate.product_line_id == current_tpl.product_line_id,
            ChecklistTemplate.name == current_tpl.name,
            ChecklistTemplate.version == data.target_version,
        )
        .first()
    )
    if not target_tpl:
        raise HTTPException(status_code=400, detail=f"目标版本 v{data.target_version} 不存在")
    if target_tpl.id == current_tpl.id and current_tpl.status == "active":
        raise HTTPException(status_code=400, detail="当前模板已是激活版本，无需回滚")
    active_tpl = (
        db.query(ChecklistTemplate)
        .filter(
            ChecklistTemplate.product_line_id == current_tpl.product_line_id,
            ChecklistTemplate.name == current_tpl.name,
            ChecklistTemplate.status == "active",
        )
        .first()
    )
    if active_tpl:
        active_tpl.status = "archived"
    target_tpl.status = "active"
    _log(db, data.operated_by, "rollback_template", "template", template_id,
         f"rollback to v{data.target_version}")
    db.commit()
    return {
        "detail": "回滚完成",
        "activated_template_id": target_tpl.id,
        "activated_version": target_tpl.version,
    }


@router.post("/{template_id}/items", response_model=TemplateItemOut)
def add_template_item(template_id: int, data: TemplateItemCreate, db: Session = Depends(get_db)):
    tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    item = TemplateItem(
        template_id=template_id,
        category=data.category,
        name=data.name,
        description=data.description,
        standard=data.standard,
        sort_order=data.sort_order,
        is_required=data.is_required,
        score_weight=data.score_weight,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{template_id}/items/{item_id}")
def delete_template_item(template_id: int, item_id: int, db: Session = Depends(get_db)):
    item = db.query(TemplateItem).filter(TemplateItem.id == item_id, TemplateItem.template_id == template_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="检查项不存在")
    db.delete(item)
    db.commit()
    return {"detail": "删除成功"}


@router.delete("/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    if tpl.status == "active":
        active_execs = db.query(Execution).filter(Execution.template_id == template_id, Execution.status == "in_progress").count()
        if active_execs > 0:
            raise HTTPException(status_code=400, detail=f"该模板有 {active_execs} 个进行中的执行记录，不能删除")
    db.delete(tpl)
    db.commit()
    return {"detail": "删除成功"}
