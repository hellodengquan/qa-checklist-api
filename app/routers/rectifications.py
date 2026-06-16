from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Rectification, NonConformance, RectificationTransfer, TransferApproval, AuditLog, TransferApprovalChain
from app.schemas import (
    RectificationCreate, RectificationUpdate, RectificationOut,
    RectificationTransferCreate, RectificationTransferOut,
    TransferApprovalRequest, TransferApprovalOut,
    TransferChainCreate, TransferChainStepOut, TransferChainApproveRequest,
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


@router.post("/{rectification_id}/transfer-request", response_model=RectificationTransferOut)
def request_transfer(rectification_id: int, data: RectificationTransferCreate, db: Session = Depends(get_db)):
    rect = db.query(Rectification).filter(Rectification.id == rectification_id).first()
    if not rect:
        raise HTTPException(status_code=404, detail="整改记录不存在")
    if rect.status in ("completed", "verified"):
        raise HTTPException(status_code=400, detail="已完成的整改单不能申请转移")
    if rect.pending_transfer_id is not None:
        pending = db.query(RectificationTransfer).filter(RectificationTransfer.id == rect.pending_transfer_id).first()
        if pending and pending.status == "pending":
            raise HTTPException(status_code=400, detail="已有待审批的转移申请")
    if data.to_person == rect.responsible_person:
        raise HTTPException(status_code=400, detail="不能转移给当前负责人")
    now = datetime.utcnow()
    transfer = RectificationTransfer(
        rectification_id=rectification_id,
        from_person=rect.responsible_person,
        to_person=data.to_person,
        reason=data.reason,
        status="pending",
        requested_by=data.requested_by or rect.responsible_person,
        requested_at=now,
    )
    db.add(transfer)
    db.flush()
    rect.pending_transfer_id = transfer.id
    _log(db, data.requested_by or rect.responsible_person, "request_transfer", "rectification", rectification_id,
         f"from={transfer.from_person} to={data.to_person}")
    db.commit()
    db.refresh(transfer)
    return transfer


@router.post("/{rectification_id}/transfer-approve", response_model=RectificationOut)
def approve_transfer(rectification_id: int, data: TransferApprovalRequest, db: Session = Depends(get_db)):
    rect = db.query(Rectification).filter(Rectification.id == rectification_id).first()
    if not rect:
        raise HTTPException(status_code=404, detail="整改记录不存在")
    if rect.pending_transfer_id is None:
        raise HTTPException(status_code=400, detail="没有待审批的转移申请")
    transfer = db.query(RectificationTransfer).filter(RectificationTransfer.id == rect.pending_transfer_id).first()
    if not transfer or transfer.status != "pending":
        raise HTTPException(status_code=400, detail="当前没有待审批的转移申请")
    if data.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision 只能是 approved 或 rejected")
    now = datetime.utcnow()
    approval = TransferApproval(
        transfer_id=transfer.id,
        approver=data.approver,
        decision=data.decision,
        comment=data.comment,
        approved_at=now,
    )
    db.add(approval)
    transfer.approver = data.approver
    transfer.approved_at = now
    transfer.approval_comment = data.comment
    if data.decision == "approved":
        transfer.status = "completed"
        transfer.transferred_at = now
        rect.responsible_person = transfer.to_person
        rect.pending_transfer_id = None
        _log(db, data.approver, "approve_transfer", "rectification", rectification_id,
             f"approved: {transfer.from_person}->{transfer.to_person}")
    else:
        transfer.status = "rejected"
        rect.pending_transfer_id = None
        _log(db, data.approver, "reject_transfer", "rectification", rectification_id, data.comment)
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
    now = datetime.utcnow()
    transfer = RectificationTransfer(
        rectification_id=rectification_id,
        from_person=rect.responsible_person,
        to_person=data.to_person,
        reason=data.reason,
        status="completed",
        approver=data.requested_by,
        transferred_at=now,
        approved_at=now,
        requested_by=data.requested_by or rect.responsible_person,
        requested_at=now,
    )
    db.add(transfer)
    rect.responsible_person = data.to_person
    rect.pending_transfer_id = None
    _log(db, data.requested_by or rect.responsible_person, "direct_transfer", "rectification", rectification_id,
         f"from={transfer.from_person} to={data.to_person}")
    db.commit()
    db.refresh(rect)
    return rect


@router.get("/{rectification_id}/transfers", response_model=list[RectificationTransferOut])
def list_transfers(rectification_id: int, db: Session = Depends(get_db)):
    rect = db.query(Rectification).filter(Rectification.id == rectification_id).first()
    if not rect:
        raise HTTPException(status_code=404, detail="整改记录不存在")
    return db.query(RectificationTransfer).filter(RectificationTransfer.rectification_id == rectification_id).order_by(RectificationTransfer.requested_at.desc()).all()


@router.get("/{rectification_id}/transfer-approvals", response_model=list[TransferApprovalOut])
def list_transfer_approvals(rectification_id: int, db: Session = Depends(get_db)):
    rect = db.query(Rectification).filter(Rectification.id == rectification_id).first()
    if not rect:
        raise HTTPException(status_code=404, detail="整改记录不存在")
    transfer_ids = [t.id for t in rect.transfers]
    if not transfer_ids:
        return []
    return db.query(TransferApproval).filter(TransferApproval.transfer_id.in_(transfer_ids)).order_by(TransferApproval.approved_at.desc()).all()


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


# ============ RectificationTransfer 多级签字审批链 ============

@router.post("/{rectification_id}/transfer-chain", response_model=list[TransferChainStepOut])
def create_transfer_approval_chain(rectification_id: int, data: TransferChainCreate, db: Session = Depends(get_db)):
    transfer = db.query(RectificationTransfer).filter(RectificationTransfer.id == data.transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="整改委托单不存在")
    if transfer.rectification_id != rectification_id:
        raise HTTPException(status_code=400, detail="委托单不属于该整改记录")
    if not data.approvers:
        raise HTTPException(status_code=400, detail="至少需要一个审批人")
    transfer.approval_mode = data.mode
    transfer.required_approvers = ",".join(data.approvers)
    transfer.current_approver_index = 0 if data.mode == "serial" else 0
    transfer.approval_chain_status = "pending"
    steps = []
    for idx, approver in enumerate(data.approvers):
        step = TransferApprovalChain(
            transfer_id=transfer.id,
            approver=approver,
            step_index=idx,
            decision="pending",
        )
        db.add(step)
        steps.append(step)
    _log(db, transfer.requested_by or "system", "create_transfer_chain",
         "transfer", transfer.id, f"mode={data.mode}, approvers={len(data.approvers)}")
    db.commit()
    for s in steps:
        db.refresh(s)
    return steps


@router.post("/{rectification_id}/transfer-chain/{transfer_id}/approve", response_model=TransferChainStepOut)
def approve_transfer_chain_step(rectification_id: int, transfer_id: int, data: TransferChainApproveRequest, db: Session = Depends(get_db)):
    transfer = db.query(RectificationTransfer).filter(RectificationTransfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="整改委托单不存在")
    if transfer.rectification_id != rectification_id:
        raise HTTPException(status_code=400, detail="委托单不属于该整改记录")
    steps = db.query(TransferApprovalChain).filter(
        TransferApprovalChain.transfer_id == transfer_id
    ).order_by(TransferApprovalChain.step_index).all()
    if not steps:
        raise HTTPException(status_code=400, detail="该委托单还未创建多级审批链")
    now = datetime.utcnow()
    if transfer.approval_mode == "serial":
        current_idx = transfer.current_approver_index or 0
        if current_idx >= len(steps):
            raise HTTPException(status_code=400, detail="该审批链已完成")
        current_step = steps[current_idx]
        if current_step.approver != data.approver:
            raise HTTPException(status_code=403, detail=f"当前审批人应为 {current_step.approver}，不是 {data.approver}")
        current_step.decision = data.decision
        current_step.comment = data.comment
        current_step.decided_at = now
        if data.decision == "rejected":
            transfer.approval_chain_status = "rejected"
            transfer.status = "rejected"
            db.add(TransferApproval(transfer_id=transfer.id, approver=data.approver,
                                    decision="rejected", comment=data.comment, approved_at=now))
        elif data.decision == "approved":
            next_idx = current_idx + 1
            if next_idx >= len(steps):
                transfer.approval_chain_status = "completed"
                transfer.current_approver_index = next_idx
                rect = db.query(Rectification).filter(Rectification.id == transfer.rectification_id).first()
                if rect:
                    rect.responsible_person = transfer.to_person
                    rect.pending_transfer_id = None
                transfer.status = "completed"
                db.add(TransferApproval(transfer_id=transfer.id, approver=data.approver,
                                        decision="approved", comment=data.comment, approved_at=now))
            else:
                transfer.current_approver_index = next_idx
        db.commit()
        db.refresh(current_step)
        return current_step
    else:
        my_step = None
        for s in steps:
            if s.approver == data.approver:
                my_step = s
                break
        if not my_step:
            raise HTTPException(status_code=403, detail=f"审批人 {data.approver} 不在审批链中")
        if my_step.decision != "pending":
            raise HTTPException(status_code=400, detail="该审批人已完成审批")
        my_step.decision = data.decision
        my_step.comment = data.comment
        my_step.decided_at = now
        approved_count = sum(1 for s in steps if s.decision == "approved")
        rejected_count = sum(1 for s in steps if s.decision == "rejected")
        if rejected_count > 0:
            transfer.approval_chain_status = "rejected"
            transfer.status = "rejected"
            db.add(TransferApproval(transfer_id=transfer.id, approver=data.approver,
                                    decision="rejected", comment=data.comment, approved_at=now))
        elif approved_count == len(steps):
            transfer.approval_chain_status = "completed"
            rect = db.query(Rectification).filter(Rectification.id == transfer.rectification_id).first()
            if rect:
                rect.responsible_person = transfer.to_person
                rect.pending_transfer_id = None
            transfer.status = "completed"
            db.add(TransferApproval(transfer_id=transfer.id, approver=data.approver,
                                    decision="approved", comment=data.comment, approved_at=now))
        else:
            transfer.approval_chain_status = "in_progress"
        db.commit()
        db.refresh(my_step)
        return my_step


@router.get("/{rectification_id}/transfer-chain/{transfer_id}", response_model=list[TransferChainStepOut])
def list_transfer_chain_steps(rectification_id: int, transfer_id: int, db: Session = Depends(get_db)):
    transfer = db.query(RectificationTransfer).filter(RectificationTransfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="整改委托单不存在")
    if transfer.rectification_id != rectification_id:
        raise HTTPException(status_code=400, detail="委托单不属于该整改记录")
    return db.query(TransferApprovalChain).filter(
        TransferApprovalChain.transfer_id == transfer_id
    ).order_by(TransferApprovalChain.step_index).all()
