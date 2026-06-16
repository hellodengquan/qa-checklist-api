from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import ChecklistTemplate, TemplateItem, ProductLine
from app.schemas import (
    TemplateCreate, TemplateOut, TemplateItemCreate, TemplateItemOut, TemplateVersionOut
)

router = APIRouter(prefix="/api/templates", tags=["清单模板管理"])


@router.post("", response_model=TemplateOut)
def create_template(data: TemplateCreate, db: Session = Depends(get_db)):
    pl = db.query(ProductLine).filter(ProductLine.id == data.product_line_id).first()
    if not pl:
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
    db.delete(tpl)
    db.commit()
    return {"detail": "删除成功"}
