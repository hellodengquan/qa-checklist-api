from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Review, Execution
from app.schemas import ReviewCreate, ReviewOut

router = APIRouter(prefix="/api/reviews", tags=["协作复核"])


@router.post("/{execution_id}", response_model=ReviewOut)
def create_review(execution_id: int, data: ReviewCreate, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status != "completed":
        raise HTTPException(status_code=400, detail="只有已完成的执行记录才能复核")
    if data.result not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="复核结果只能是 approved 或 rejected")
    review = Review(
        execution_id=execution_id,
        reviewer=data.reviewer,
        result=data.result,
        comment=data.comment,
    )
    db.add(review)
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
