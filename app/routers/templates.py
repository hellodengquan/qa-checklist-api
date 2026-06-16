from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import ChecklistTemplate, TemplateItem, Execution, ExecutionItem, AuditLog
from app.schemas import (
    TemplateCreate, TemplateOut, TemplateItemCreate, TemplateItemOut,
    TemplateVersionOut, TemplateMigrateRequest, TemplateRollbackRequest,
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
