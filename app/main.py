from app.database import Base, engine, ensure_indexes
from app.models import (  # noqa: F401
    ProductLine, ChecklistTemplate, TemplateItem,
    Execution, ExecutionItem, ScoreRevision,
    NonConformance, Rectification, RectificationTransfer,
    Review, User, AuditLog,
    NCEscalationRule, TransferApproval, ArbitrationConsensus, RBACMatrix,
)

Base.metadata.create_all(bind=engine)
ensure_indexes()

from fastapi import FastAPI
from app.routers import product_lines, templates, executions, rectifications, reviews, auth

app = FastAPI(
    title="质检检查清单 API",
    description="按产品线维护清单模板、抽取批次执行、记录每项打分与不符合处置，支持多人协作复核；"
                "含 ScoreRevision 回放、RectificationTransfer 审批、executions 异常流转、NC 升级阈值、"
                "仲裁终态共识、版本回滚迁移成本评估、RBAC 矩阵、审计日志聚合查询。",
    version="2.1.0",
)

app.include_router(product_lines.router)
app.include_router(templates.router)
app.include_router(executions.router)
app.include_router(rectifications.router)
app.include_router(reviews.router)
app.include_router(auth.router)


@app.get("/")
def root():
    return {"message": "质检检查清单 API v2.1 已启动", "docs": "/docs"}
