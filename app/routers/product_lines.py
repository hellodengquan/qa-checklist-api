from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import ProductLine
from app.schemas import ProductLineCreate, ProductLineOut

router = APIRouter(prefix="/api/product-lines", tags=["产品线管理"])


@router.post("", response_model=ProductLineOut)
def create_product_line(data: ProductLineCreate, db: Session = Depends(get_db)):
    existing = db.query(ProductLine).filter(ProductLine.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="产品线名称已存在")
    obj = ProductLine(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("", response_model=list[ProductLineOut])
def list_product_lines(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    return db.query(ProductLine).offset(skip).limit(limit).all()


@router.get("/{product_line_id}", response_model=ProductLineOut)
def get_product_line(product_line_id: int, db: Session = Depends(get_db)):
    obj = db.query(ProductLine).filter(ProductLine.id == product_line_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="产品线不存在")
    return obj


@router.put("/{product_line_id}", response_model=ProductLineOut)
def update_product_line(product_line_id: int, data: ProductLineCreate, db: Session = Depends(get_db)):
    obj = db.query(ProductLine).filter(ProductLine.id == product_line_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="产品线不存在")
    dup = db.query(ProductLine).filter(ProductLine.name == data.name, ProductLine.id != product_line_id).first()
    if dup:
        raise HTTPException(status_code=400, detail="产品线名称已存在")
    obj.name = data.name
    obj.description = data.description
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{product_line_id}")
def delete_product_line(product_line_id: int, db: Session = Depends(get_db)):
    obj = db.query(ProductLine).filter(ProductLine.id == product_line_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="产品线不存在")
    db.delete(obj)
    db.commit()
    return {"detail": "删除成功"}
