from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, AuditLog
from app.schemas import UserCreate, UserUpdate, UserOut, AuditLogOut

router = APIRouter(prefix="/api/users", tags=["用户与权限"])


def _log(db: Session, username: str, action: str, rtype: str, rid: int, detail: str = ""):
    db.add(AuditLog(username=username, action=action, resource_type=rtype, resource_id=rid, detail=detail))


def get_current_user(x_user: str = Header(..., alias="X-User"), db: Session = Depends(get_db)) -> User:
    user = db.query(User).filter(User.username == x_user, User.is_active == 1).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在或已停用，请先创建用户")
    return user


def require_role(*allowed_roles: str):
    def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"权限不足，需要角色: {allowed_roles}")
        return current_user
    return checker


def get_user_product_line_ids(user: User) -> list[int]:
    if not user.product_line_ids:
        return []
    return [int(x) for x in user.product_line_ids.split(",") if x.strip()]


@router.post("", response_model=UserOut)
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")
    valid_roles = ("admin", "qa_manager", "inspector", "viewer")
    if data.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"无效角色，可选: {valid_roles}")
    pl_ids = ",".join(str(i) for i in data.product_line_ids)
    user = User(
        username=data.username,
        display_name=data.display_name,
        role=data.role,
        product_line_ids=pl_ids,
        is_active=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("", response_model=list[UserOut])
def list_users(
    role: str | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(require_role("admin", "qa_manager")),
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if role:
        q = q.filter(User.role == role)
    return q.offset(skip).limit(limit).all()


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, current_user: User = Depends(require_role("admin", "qa_manager")), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, current_user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if data.display_name is not None:
        user.display_name = data.display_name
    if data.role is not None:
        valid_roles = ("admin", "qa_manager", "inspector", "viewer")
        if data.role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"无效角色，可选: {valid_roles}")
        user.role = data.role
    if data.product_line_ids is not None:
        user.product_line_ids = ",".join(str(i) for i in data.product_line_ids)
    if data.is_active is not None:
        user.is_active = data.is_active
    _log(db, current_user.username, "update_user", "user", user_id)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def delete_user(user_id: int, current_user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    _log(db, current_user.username, "delete_user", "user", user_id)
    db.delete(user)
    db.commit()
    return {"detail": "删除成功"}


@router.get("/audit-logs/list", response_model=list[AuditLogOut])
def list_audit_logs(
    username: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(require_role("admin", "qa_manager")),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog)
    if username:
        q = q.filter(AuditLog.username == username)
    if action:
        q = q.filter(AuditLog.action == action)
    if resource_type:
        q = q.filter(AuditLog.resource_type == resource_type)
    return q.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/scope/product-lines", response_model=list[int])
def get_my_product_lines(current_user: User = Depends(get_current_user)):
    return get_user_product_line_ids(current_user)
