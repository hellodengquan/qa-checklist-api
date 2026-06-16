from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Rectification, NonConformance
from app.schemas import RectificationCreate, RectificationUpdate, RectificationOut

router = APIRouter(prefix="/api/rectifications", tags=["整改追踪"])


@router.post("/{nonconformance_id}", response_model=RectificationOut)
def create_rectification(nonconformance_id: int, data: RectificationCreate, db: Session = Depends(get_db)):
    nc = db.query(NonConformance).filter(NonConformance.id == nonconformance_id).first()
    if not nc:
        raise HTTPException(status_code=404, detail="不符合记录不存在")
    existing = db.query(Rectification).filter(Rectification.nonconformance_id == nonconformance_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="该不符合记录已有整改单")
    rect = Rectification(
        nonconformance_id=nonconformance_id,
        action_plan=data.action_plan,
        responsible_person=data.responsible_person,
        due_date=data.due_date,
        status="pending",
        remark=data.remark,
    )
    db.add(rect)
    db.commit()
    db.refresh(rect)
    return rect


@router.get("", response_model=list[RectificationOut])
def list_rectifications(
    status: str | None = None,
    responsible_person: str | None = None,
    overdue: bool | None = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(Rectification)
    if status:
        q = q.filter(Rectification.status == status)
    if responsible_person:
        q = q.filter(Rectification.responsible_person == responsible_person)
    if overdue:
        now = datetime.utcnow()
        q = q.filter(Rectification.due_date < now, Rectification.status != "verified")
    return q.order_by(Rectification.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{rectification_id}", response_model=RectificationOut)
def get_rectification(rectification_id: int, db: Session = Depends(get_db)):
    rect = db.query(Rectification).filter(Rectification.id == rectification_id).first()
    if not rect:
        raise HTTPException(status_code=404, detail="整改记录不存在")
    return rect


@router.put("/{rectification_id}", response_model=RectificationOut)
def update_rectification(rectification_id: int, data: RectificationUpdate, db: Session = Depends(get_db)):
    rect = db.query(Rectification).filter(Rectification.id == rectification_id).first()
    if not rect:
        raise HTTPException(status_code=404, detail="整改记录不存在")
    if data.status is not None:
        valid = ("pending", "in_progress", "completed", "verified")
        if data.status not in valid:
            raise HTTPException(status_code=400, detail=f"无效状态，可选: {valid}")
        rect.status = data.status
    if data.completed_at is not None:
        rect.completed_at = data.completed_at
    if data.verified_by is not None:
        rect.verified_by = data.verified_by
    if data.verified_at is not None:
        rect.verified_at = data.verified_at
    if data.remark is not None:
        rect.remark = data.remark
    db.commit()
    db.refresh(rect)
    return rect
