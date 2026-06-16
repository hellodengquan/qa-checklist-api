from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import func, cast, String
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, AuditLog, RBACMatrix
from app.schemas import (
    UserCreate, UserUpdate, UserOut, AuditLogOut, AuditLogAggOut,
    RBACEntryCreate, RBACEntryOut, RBACMatrixOut,
)

router = APIRouter(prefix="/api/users", tags=["用户与权限"])

DEFAULT_RBAC = [
    ("admin", "*", "*", "超级管理员，拥有全部权限"),
    ("qa_manager", "execution", "create", "创建执行记录"),
    ("qa_manager", "execution", "read", "查看执行记录"),
    ("qa_manager", "execution", "modify_score", "修改执行打分"),
    ("qa_manager", "execution", "complete", "完成/强制完成执行"),
    ("qa_manager", "execution", "reopen", "重开执行记录"),
    ("qa_manager", "execution", "terminate", "终止执行记录"),
    ("qa_manager", "execution", "suspend", "暂停/恢复执行"),
    ("qa_manager", "execution", "score_replay", "回放打分修订"),
    ("qa_manager", "nonconformance", "create", "创建不符合记录"),
    ("qa_manager", "nonconformance", "escalate", "升级不符合"),
    ("qa_manager", "rectification", "transfer", "整改单直接转移"),
    ("qa_manager", "rectification", "transfer_approve", "审批整改转移"),
    ("qa_manager", "rectification", "read", "查看整改单"),
    ("qa_manager", "review", "create", "提交复核"),
    ("qa_manager", "review", "arbitrate", "执行仲裁"),
    ("qa_manager", "review", "consensus_vote", "共识投票"),
    ("qa_manager", "template", "create", "创建模板"),
    ("qa_manager", "template", "edit", "编辑模板"),
    ("qa_manager", "template", "activate", "激活模板"),
    ("qa_manager", "template", "migrate", "迁移模板"),
    ("qa_manager", "template", "rollback", "回滚模板"),
    ("qa_manager", "template", "estimate", "评估迁移/回滚成本"),
    ("qa_manager", "user", "read", "查看用户"),
    ("qa_manager", "user", "update_role", "更新角色"),
    ("qa_manager", "audit_log", "read", "查看审计日志"),
    ("qa_manager", "audit_log", "aggregate", "聚合查询审计日志"),
    ("qa_manager", "rbac", "read", "查看RBAC矩阵"),
    ("inspector", "execution", "create", "创建执行记录"),
    ("inspector", "execution", "read", "查看本人执行记录"),
    ("inspector", "execution", "score", "对执行记录打分"),
    ("inspector", "execution", "complete", "提交执行完成"),
    ("inspector", "nonconformance", "create", "创建不符合记录"),
    ("inspector", "rectification", "read", "查看本人相关整改"),
    ("inspector", "rectification", "transfer_request", "申请整改转移"),
    ("inspector", "review", "create", "提交复核"),
    ("inspector", "review", "consensus_vote", "参与共识投票"),
    ("inspector", "user", "read_self", "查看本人信息"),
    ("viewer", "execution", "read", "只读查看执行记录"),
    ("viewer", "template", "read", "只读查看模板"),
    ("viewer", "nonconformance", "read", "只读查看不符合"),
    ("viewer", "rectification", "read", "只读查看整改"),
    ("viewer", "review", "read", "只读查看复核"),
    ("viewer", "user", "read_self", "查看本人信息"),
]


def _log(db: Session, username: str, action: str, rtype: str, rid: int, detail: str = ""):
    db.add(AuditLog(username=username, action=action, resource_type=rtype, resource_id=rid, detail=detail))


def ensure_default_rbac(db: Session):
    existing_count = db.query(RBACMatrix).count()
    if existing_count > 0:
        return
    for role, resource, action, desc in DEFAULT_RBAC:
        entry = RBACMatrix(role=role, resource=resource, action=action, description=desc)
        db.add(entry)
    db.commit()


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


def require_permission(resource: str, action: str):
    def checker(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        if current_user.role == "admin":
            return current_user
        has_perm = db.query(RBACMatrix).filter(
            RBACMatrix.role == current_user.role,
            ((RBACMatrix.resource == resource) | (RBACMatrix.resource == "*")),
            ((RBACMatrix.action == action) | (RBACMatrix.action == "*")),
        ).first()
        if not has_perm:
            raise HTTPException(status_code=403, detail=f"权限不足，缺少 {resource}.{action}")
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
    ensure_default_rbac(db)
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
    return q.order_by(User.id.asc()).offset(skip).limit(limit).all()


# --- /rbac, /audit-logs, /scope 必须在 /{user_id} 之前定义，否则会被 user_id 路径参数吞掉 ---

@router.post("/rbac/bootstrap")
def bootstrap_rbac(db: Session = Depends(get_db)):
    db.query(RBACMatrix).delete()
    db.commit()
    for role, resource, action, desc in DEFAULT_RBAC:
        entry = RBACMatrix(role=role, resource=resource, action=action, description=desc)
        db.add(entry)
    db.commit()
    return {"detail": "RBAC 矩阵已重置为默认配置", "count": len(DEFAULT_RBAC)}


@router.post("/rbac", response_model=RBACEntryOut)
def create_rbac_entry(
    data: RBACEntryCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    existing = db.query(RBACMatrix).filter(
        RBACMatrix.role == data.role,
        RBACMatrix.resource == data.resource,
        RBACMatrix.action == data.action,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该权限条目已存在")
    entry = RBACMatrix(
        role=data.role,
        resource=data.resource,
        action=data.action,
        description=data.description,
    )
    db.add(entry)
    _log(db, current_user.username, "create_rbac", "rbac", 0,
         f"{data.role}:{data.resource}.{data.action}")
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/rbac", response_model=list[RBACEntryOut])
def list_rbac(
    role: str | None = None,
    resource: str | None = None,
    action: str | None = None,
    current_user: User = Depends(require_role("admin", "qa_manager")),
    db: Session = Depends(get_db),
):
    ensure_default_rbac(db)
    q = db.query(RBACMatrix)
    if role:
        q = q.filter(RBACMatrix.role == role)
    if resource:
        q = q.filter(RBACMatrix.resource == resource)
    if action:
        q = q.filter(RBACMatrix.action == action)
    return q.order_by(RBACMatrix.role, RBACMatrix.resource, RBACMatrix.action).all()


@router.get("/rbac/matrix", response_model=list[RBACMatrixOut])
def get_rbac_matrix(
    current_user: User = Depends(require_role("admin", "qa_manager")),
    db: Session = Depends(get_db),
):
    ensure_default_rbac(db)
    entries = db.query(RBACMatrix).order_by(
        RBACMatrix.role, RBACMatrix.resource, RBACMatrix.action
    ).all()
    grouped = {}
    for e in entries:
        grouped.setdefault(e.role, []).append({
            "resource": e.resource,
            "action": e.action,
            "description": e.description,
        })
    return [RBACMatrixOut(role=r, permissions=perms) for r, perms in grouped.items()]


@router.get("/rbac/check")
def check_rbac(
    resource: str,
    action: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_default_rbac(db)
    if current_user.role == "admin":
        return {"allowed": True, "role": current_user.role, "resource": resource, "action": action}
    has_perm = db.query(RBACMatrix).filter(
        RBACMatrix.role == current_user.role,
        ((RBACMatrix.resource == resource) | (RBACMatrix.resource == "*")),
        ((RBACMatrix.action == action) | (RBACMatrix.action == "*")),
    ).first()
    return {
        "allowed": has_perm is not None,
        "role": current_user.role,
        "resource": resource,
        "action": action,
    }


@router.delete("/rbac/{entry_id}")
def delete_rbac_entry(
    entry_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    entry = db.query(RBACMatrix).filter(RBACMatrix.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="RBAC 条目不存在")
    db.delete(entry)
    _log(db, current_user.username, "delete_rbac", "rbac", entry_id,
         f"{entry.role}:{entry.resource}.{entry.action}")
    db.commit()
    return {"detail": "删除成功"}


@router.get("/audit-logs/list", response_model=list[AuditLogOut])
def list_audit_logs(
    username: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    skip: int = 0,
    limit: int = 100,
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
    if resource_id is not None:
        q = q.filter(AuditLog.resource_id == resource_id)
    if start_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            q = q.filter(AuditLog.created_at >= start)
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d")
            end = end.replace(hour=23, minute=59, second=59)
            q = q.filter(AuditLog.created_at <= end)
        except ValueError:
            pass
    return q.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/audit-logs/aggregate", response_model=list[AuditLogAggOut])
def aggregate_audit_logs(
    group_by: str = "date,username,action",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 200,
    current_user: User = Depends(require_role("admin", "qa_manager")),
    db: Session = Depends(get_db),
):
    group_columns = []
    valid_groups = []
    for g in group_by.split(","):
        g = g.strip()
        if g == "date":
            valid_groups.append(func.strftime("%Y-%m-%d", AuditLog.created_at).label("date"))
        elif g == "username":
            valid_groups.append(AuditLog.username.label("username"))
        elif g == "action":
            valid_groups.append(AuditLog.action.label("action"))
        elif g == "resource_type":
            valid_groups.append(AuditLog.resource_type.label("resource_type"))
    if not valid_groups:
        raise HTTPException(status_code=400,
                            detail="group_by 可选字段: date, username, action, resource_type")
    q = db.query(*valid_groups, func.count(AuditLog.id).label("count"))
    if start_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            q = q.filter(AuditLog.created_at >= start)
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d")
            end = end.replace(hour=23, minute=59, second=59)
            q = q.filter(AuditLog.created_at <= end)
        except ValueError:
            pass
    q = q.group_by(*valid_groups).order_by(func.count(AuditLog.id).desc()).limit(limit)
    rows = q.all()
    result = []
    for row in rows:
        d = dict(row._mapping)
        result.append(AuditLogAggOut(
            date=str(d.get("date", "")),
            username=d.get("username", ""),
            action=d.get("action", ""),
            count=d.get("count", 0),
        ))
    return result


@router.get("/scope/product-lines", response_model=list[int])
def get_my_product_lines(current_user: User = Depends(get_current_user)):
    return get_user_product_line_ids(current_user)


# --- /{user_id} 相关路由放最后，避免吞掉具体路径 ---

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
