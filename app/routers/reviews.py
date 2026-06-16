from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Review, Execution, AuditLog
from app.schemas import ReviewCreate, ReviewOut, ArbitrationRequest, ReopenRequest

router = APIRouter(prefix="/api/reviews", tags=["协作复核"])


def _log(db: Session, username: str, action: str, rtype: str, rid: int, detail: str = ""):
    db.add(AuditLog(username=username, action=action, resource_type=rtype, resource_id=rid, detail=detail))


@router.post("/{execution_id}", response_model=ReviewOut)
def create_review(execution_id: int, data: ReviewCreate, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status not in ("completed", "arbitrated"):
        raise HTTPException(status_code=400, detail="只有已完成或已仲裁的执行记录才能复核")
    if data.result not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="复核结果只能是 approved 或 rejected")
    existing = db.query(Review).filter(
        Review.execution_id == execution_id, Review.reviewer == data.reviewer
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该复核人已提交过复核，不能重复提交")
    review = Review(
        execution_id=execution_id,
        reviewer=data.reviewer,
        result=data.result,
        comment=data.comment,
    )
    db.add(review)
    _log(db, data.reviewer, "create_review", "execution", execution_id, f"result={data.result}")
    db.commit()
    db.refresh(review)
    return review


@router.post("/{execution_id}/arbitrate", response_model=ReviewOut)
def arbitrate_execution(execution_id: int, data: ArbitrationRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status not in ("completed", "arbitrated"):
        raise HTTPException(status_code=400, detail="只有已完成或已仲裁的执行记录才能进行仲裁")
    reviews = db.query(Review).filter(Review.execution_id == execution_id).all()
    if len(reviews) < 2:
        raise HTTPException(status_code=400, detail="至少需要2条复核记录才能仲裁")
    approved_count = sum(1 for r in reviews if r.result == "approved")
    rejected_count = sum(1 for r in reviews if r.result == "rejected")
    has_conflict = approved_count > 0 and rejected_count > 0
    if not has_conflict and data.result not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="仲裁结果只能是 approved 或 rejected")
    if data.result not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="仲裁结果只能是 approved 或 rejected")
    existing_arbitrator = db.query(Review).filter(
        Review.execution_id == execution_id, Review.reviewer == data.arbitrator
    ).first()
    if existing_arbitrator:
        raise HTTPException(status_code=400, detail="仲裁人已提交过复核，不能同时仲裁")
    review = Review(
        execution_id=execution_id,
        reviewer=f"[仲裁]{data.arbitrator}",
        result=data.result,
        comment=data.comment,
    )
    db.add(review)
    execution.arbitration_result = data.result
    execution.arbitration_by = data.arbitrator
    execution.arbitration_at = datetime.utcnow()
    execution.arbitration_comment = data.comment
    execution.status = "arbitrated"
    _log(db, data.arbitrator, "arbitrate", "execution", execution_id, f"result={data.result}")
    db.commit()
    db.refresh(review)
    return review


@router.post("/{execution_id}/reopen", response_model=ReviewOut)
def reopen_after_review(execution_id: int, data: ReopenRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status not in ("completed", "arbitrated"):
        raise HTTPException(status_code=400, detail="只有已完成或已仲裁的执行记录才能驳回重开")
    reviews = db.query(Review).filter(Review.execution_id == execution_id).all()
    if not reviews:
        raise HTTPException(status_code=400, detail="没有复核记录，请使用执行记录的重开接口")
    review = Review(
        execution_id=execution_id,
        reviewer=f"[驳回重开]{data.operated_by}",
        result="reopen",
        comment=data.reason,
    )
    db.add(review)
    execution.status = "in_progress"
    execution.arbitration_result = None
    execution.arbitration_by = ""
    execution.arbitration_at = None
    execution.arbitration_comment = ""
    execution.force_completed = 0
    _log(db, data.operated_by, "reopen_after_review", "execution", execution_id, data.reason)
    db.commit()
    db.refresh(review)
    return review


@router.get("/execution/{execution_id}", response_model=list[ReviewOut])
def list_reviews_for_execution(execution_id: int, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return db.query(Review).filter(Review.execution_id == execution_id).order_by(Review.reviewed_at.desc()).all()


@router.get("", response_model=list[ReviewOut])
def list_reviews(
    reviewer: str | None = None,
    result: str | None = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(Review)
    if reviewer:
        q = q.filter(Review.reviewer == reviewer)
    if result:
        q = q.filter(Review.result == result)
    return q.order_by(Review.reviewed_at.desc()).offset(skip).limit(limit).all()
