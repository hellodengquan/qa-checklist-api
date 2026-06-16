from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Review, Execution, AuditLog, ArbitrationConsensus
from app.schemas import (
    ReviewCreate, ReviewOut, ArbitrationRequest, ReopenRequest,
    ConsensusVote, ConsensusOut, ConsensusCheckRequest,
)

router = APIRouter(prefix="/api/reviews", tags=["协作复核"])


def _log(db: Session, username: str, action: str, rtype: str, rid: int, detail: str = ""):
    db.add(AuditLog(username=username, action=action, resource_type=rtype, resource_id=rid, detail=detail))


@router.post("/{execution_id}", response_model=ReviewOut)
def create_review(execution_id: int, data: ReviewCreate, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status not in ("completed", "arbitrated", "in_consensus"):
        raise HTTPException(status_code=400, detail="当前状态不能复核")
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
    if execution.status not in ("completed", "arbitrated", "in_consensus"):
        raise HTTPException(status_code=400, detail="当前状态不能仲裁")
    reviews = db.query(Review).filter(Review.execution_id == execution_id).all()
    if len(reviews) < 2:
        raise HTTPException(status_code=400, detail="至少需要2条复核记录才能仲裁")
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


@router.post("/{execution_id}/consensus-vote", response_model=ConsensusOut)
def cast_consensus_vote(execution_id: int, data: ConsensusVote, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status not in ("completed", "arbitrated", "in_consensus"):
        raise HTTPException(status_code=400, detail="当前状态不允许共识投票")
    if data.vote not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="共识投票只能是 approved 或 rejected")
    existing = db.query(ArbitrationConsensus).filter(
        ArbitrationConsensus.execution_id == execution_id,
        ArbitrationConsensus.voter == data.voter,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该投票人已投过票")
    if execution.status != "in_consensus":
        execution.status = "in_consensus"
    vote = ArbitrationConsensus(
        execution_id=execution_id,
        voter=data.voter,
        vote=data.vote,
        comment=data.comment,
    )
    db.add(vote)
    _log(db, data.voter, "consensus_vote", "execution", execution_id, f"vote={data.vote}")
    db.commit()
    db.refresh(vote)
    return vote


@router.post("/{execution_id}/consensus-check", response_model=dict)
def check_consensus(
    execution_id: int, data: ConsensusCheckRequest, db: Session = Depends(get_db),
):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    votes = db.query(ArbitrationConsensus).filter(
        ArbitrationConsensus.execution_id == execution_id,
    ).all()
    total = len(votes)
    if total == 0:
        return {
            "execution_id": execution_id,
            "total_voters": 0,
            "approved_count": 0,
            "rejected_count": 0,
            "ratio_approved": 0.0,
            "reached": False,
            "final_result": None,
        }
    min_voters = data.min_voters or 2
    threshold_ratio = data.threshold_ratio or 0.6
    approved_count = sum(1 for v in votes if v.vote == "approved")
    rejected_count = sum(1 for v in votes if v.vote == "rejected")
    ratio_approved = approved_count / total
    ratio_rejected = rejected_count / total
    reached = False
    final_result = None
    if total >= min_voters:
        if ratio_approved >= threshold_ratio:
            reached = True
            final_result = "approved"
            execution.status = "arbitrated"
            execution.arbitration_result = "approved"
            execution.arbitration_by = "[consensus]"
            execution.arbitration_at = datetime.utcnow()
            execution.arbitration_comment = (
                f"consensus reached: {approved_count}/{total} approved, ratio={ratio_approved:.2f}"
            )
        elif ratio_rejected >= threshold_ratio:
            reached = True
            final_result = "rejected"
            execution.status = "arbitrated"
            execution.arbitration_result = "rejected"
            execution.arbitration_by = "[consensus]"
            execution.arbitration_at = datetime.utcnow()
            execution.arbitration_comment = (
                f"consensus reached: {rejected_count}/{total} rejected, ratio={ratio_rejected:.2f}"
            )
    if not reached and data.final_decision_maker:
        final_result = None
        pass
    db.commit()
    db.refresh(execution)
    return {
        "execution_id": execution_id,
        "execution_status": execution.status,
        "total_voters": total,
        "min_voters_required": min_voters,
        "threshold_ratio": threshold_ratio,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "ratio_approved": round(ratio_approved, 4),
        "ratio_rejected": round(ratio_rejected, 4),
        "reached_consensus": reached,
        "final_result": final_result,
    }


@router.get("/{execution_id}/consensus-votes", response_model=list[ConsensusOut])
def list_consensus_votes(execution_id: int, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return (
        db.query(ArbitrationConsensus)
        .filter(ArbitrationConsensus.execution_id == execution_id)
        .order_by(ArbitrationConsensus.voted_at.desc())
        .all()
    )


@router.post("/{execution_id}/consensus-finalize", response_model=ReviewOut)
def finalize_by_decision_maker(
    execution_id: int, data: ArbitrationRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status != "in_consensus":
        raise HTTPException(status_code=400, detail="只有 in_consensus 状态的执行才能终态决策")
    if data.result not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="决策结果只能是 approved 或 rejected")
    review = Review(
        execution_id=execution_id,
        reviewer=f"[终态决策]{data.arbitrator}",
        result=data.result,
        comment=data.comment,
    )
    db.add(review)
    execution.arbitration_result = data.result
    execution.arbitration_by = data.arbitrator
    execution.arbitration_at = datetime.utcnow()
    execution.arbitration_comment = data.comment
    execution.status = "arbitrated"
    _log(db, data.arbitrator, "consensus_finalize", "execution", execution_id, f"result={data.result}")
    db.commit()
    db.refresh(review)
    return review


@router.post("/{execution_id}/reopen", response_model=ReviewOut)
def reopen_after_review(execution_id: int, data: ReopenRequest, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status not in ("completed", "arbitrated", "in_consensus"):
        raise HTTPException(status_code=400, detail="当前状态不能驳回重开")
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
    execution.suspended_by = ""
    execution.suspended_at = None
    execution.suspend_reason = ""
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
