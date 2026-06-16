from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Rectification, NonConformance, RectificationTransfer, AuditLog
from app.schemas import (
    RectificationCreate, RectificationUpdate, RectificationOut,
    RectificationTransferCreate, RectificationTransferOut,
)

router = APIRouter(prefix="/api/rectifications", tags=["整改追踪"])


def _log(db: Session, username: str, action: str, rtype: str, rid: int, detail: str = ""):
    db.add(AuditLog(username=username, action=action, resource_type=rtype, resource_id=rid, detail=detail))


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
    _log(db, data.responsible_person, "create_rectification", "rectification", 0, data.action_plan[:100])
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


@router.post("/{rectification_id}/transfer", response_model=RectificationOut)
def transfer_rectification(rectification_id: int, data: RectificationTransferCreate, db: Session = Depends(get_db)):
    rect = db.query(Rectification).filter(Rectification.id == rectification_id).first()
    if not rect:
        raise HTTPException(status_code=404, detail="整改记录不存在")
    if rect.status in ("completed", "verified"):
        raise HTTPException(status_code=400, detail="已完成的整改单不能转移")
    if data.to_person == rect.responsible_person:
        raise HTTPException(status_code=400, detail="不能转移给当前负责人")
    transfer = RectificationTransfer(
        rectification_id=rectification_id,
        from_person=rect.responsible_person,
        to_person=data.to_person,
        reason=data.reason,
    )
    db.add(transfer)
    rect.responsible_person = data.to_person
    _log(db, data.to_person, "transfer_rectification", "rectification", rectification_id,
         f"from={transfer.from_person} to={data.to_person}")
    db.commit()
    db.refresh(rect)
    return rect


@router.get("/{rectification_id}/transfers", response_model=list[RectificationTransferOut])
def list_transfers(rectification_id: int, db: Session = Depends(get_db)):
    rect = db.query(Rectification).filter(Rectification.id == rectification_id).first()
    if not rect:
        raise HTTPException(status_code=404, detail="整改记录不存在")
    return db.query(RectificationTransfer).filter(RectificationTransfer.rectification_id == rectification_id).order_by(RectificationTransfer.transferred_at.desc()).all()


@router.post("/{rectification_id}/reopen", response_model=RectificationOut)
def reopen_rectification(rectification_id: int, operated_by: str = "", reason: str = "", db: Session = Depends(get_db)):
    rect = db.query(Rectification).filter(Rectification.id == rectification_id).first()
    if not rect:
        raise HTTPException(status_code=404, detail="整改记录不存在")
    if rect.status not in ("completed", "verified"):
        raise HTTPException(status_code=400, detail="只有已完成或已验证的整改单才能重新打开")
    rect.status = "in_progress"
    rect.completed_at = None
    rect.verified_by = ""
    rect.verified_at = None
    _log(db, operated_by, "reopen_rectification", "rectification", rectification_id, reason)
    db.commit()
    db.refresh(rect)
    return rect
