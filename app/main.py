from app.database import Base, engine
from app.models import (  # noqa: F401
    ProductLine, ChecklistTemplate, TemplateItem,
    Execution, ExecutionItem, NonConformance, Rectification, Review,
)

Base.metadata.create_all(bind=engine)

from fastapi import FastAPI
from app.routers import product_lines, templates, executions, rectifications, reviews

app = FastAPI(
    title="质检检查清单 API",
    description="按产品线维护清单模板、抽取批次执行、记录每项打分与不符合处置，支持多人协作复核",
    version="1.0.0",
)

app.include_router(product_lines.router)
app.include_router(templates.router)
app.include_router(executions.router)
app.include_router(rectifications.router)
app.include_router(reviews.router)


@app.get("/")
def root():
    return {"message": "质检检查清单 API 已启动", "docs": "/docs"}
