from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Execution, ExecutionItem, ChecklistTemplate, TemplateItem, NonConformance
from app.schemas import (
    ExecutionCreate, ExecutionOut, ExecutionItemScore,
    BatchScoreRequest, NonConformanceCreate, NonConformanceOut
)

router = APIRouter(prefix="/api/executions", tags=["执行记录"])


@router.post("", response_model=ExecutionOut)
def create_execution(data: ExecutionCreate, db: Session = Depends(get_db)):
    tpl = db.query(ChecklistTemplate).filter(ChecklistTemplate.id == data.template_id).first()
    if not tpl:
        raise HTTPException(status_code=400, detail="模板不存在")
    if tpl.status != "active":
        raise HTTPException(status_code=400, detail="只有激活状态的模板才能创建执行记录")
    now = datetime.utcnow()
    batch_no = f"QA-{now.strftime('%Y%m%d%H%M%S')}-{tpl.product_line_id}"
    max_score = sum(item.score_weight for item in tpl.items)
    execution = Execution(
        template_id=data.template_id,
        product_line_id=tpl.product_line_id,
        batch_no=batch_no,
        status="in_progress",
        executor=data.executor,
        total_score=0.0,
        max_score=max_score,
    )
    db.add(execution)
    db.flush()
    for tpl_item in tpl.items:
        ei = ExecutionItem(
            execution_id=execution.id,
            template_item_id=tpl_item.id,
            score=0.0,
            max_score=tpl_item.score_weight,
            result="pending",
        )
        db.add(ei)
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


@router.post("/{execution_id}/cancel", response_model=ExecutionOut)
def cancel_execution(execution_id: int, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if execution.status not in ("in_progress", "completed"):
        raise HTTPException(status_code=400, detail="当前状态不允许取消")
    execution.status = "cancelled"
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/nonconformances", response_model=NonConformanceOut)
def create_nonconformance(data: NonConformanceCreate, db: Session = Depends(get_db)):
    ei = db.query(ExecutionItem).filter(ExecutionItem.id == data.execution_item_id).first()
    if not ei:
        raise HTTPException(status_code=404, detail="执行检查项不存在")
    if ei.result != "fail":
        raise HTTPException(status_code=400, detail="只有不合格的检查项才能记录不符合")
    nc = NonConformance(
        execution_item_id=data.execution_item_id,
        description=data.description,
        severity=data.severity,
        disposition=data.disposition,
        created_by=data.created_by,
    )
    db.add(nc)
    db.commit()
    db.refresh(nc)
    return nc


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
