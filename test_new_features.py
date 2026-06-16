import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

H = {"X-User": "admin01"}
H2 = {"X-User": "inspector01"}


def ok(name, resp, expected_status=(200, 201)):
    print(f"\n=== {name} ===")
    print(f"status={resp.status_code}")
    if resp.status_code not in expected_status:
        print("RESP:", resp.text[:500])
        raise SystemExit(f"FAIL {name}")
    data = resp.json()
    s = str(data)
    print("data=", s if len(s) < 600 else s[:600] + "...")
    return data


print("=" * 60)
print("TEST START v2.1 - 8 New Features")
print("=" * 60)

r = client.post("/api/users", json={
    "username": "admin01", "display_name": "Admin", "role": "admin", "product_line_ids": []
})
print("user create:", r.status_code)
r2 = client.post("/api/users", json={
    "username": "inspector01", "display_name": "Inspector", "role": "inspector", "product_line_ids": []
})
print("user2 create:", r2.status_code)

pl = ok("create product_line",
    client.post("/api/product-lines", json={"name": "PL-A", "code": "PLA", "description": "PL-A"}))
pl_id = pl["id"]

tpl = ok("create template v1", client.post("/api/templates", json={
    "product_line_id": pl_id, "name": "TPL-v1", "version": "1.0", "description": "",
    "created_by": "admin01",
    "items": [
        {"category": "外观", "name": "颜色", "description": "", "standard": "红色",
         "score_weight": 20, "is_required": True},
        {"category": "功能", "name": "通电", "description": "", "standard": "正常",
         "score_weight": 30, "is_required": True},
        {"category": "功能", "name": "按键", "description": "", "standard": "回弹",
         "score_weight": 10, "is_required": False},
    ]
}))
tpl_id = tpl["id"]
ok("activate template", client.put(f"/api/templates/{tpl_id}/status?status=active", headers=H))

print("\n\n>>>>>>>>>> 新 8 Feature 测试 <<<<<<<<<<")

# ========== Feature 7: 版本回滚迁移成本 ==========
print("\n[Feature 7] 版本回滚迁移成本")
tpl2 = ok("create template v2", client.post("/api/templates", json={
    "product_line_id": pl_id, "name": "TPL-v1", "version": "2.0", "description": "v2",
    "created_by": "admin01",
    "items": [
        {"category": "外观", "name": "颜色", "description": "", "standard": "蓝色",
         "score_weight": 20, "is_required": True},
        {"category": "功能", "name": "通电", "description": "", "standard": "正常",
         "score_weight": 40, "is_required": True},
        {"category": "安全", "name": "接地", "description": "", "standard": "有效",
         "score_weight": 50, "is_required": True},
    ]
}))
cost = ok("estimate migrate v2", client.get(f"/api/templates/{tpl2['id']}/estimate-migrate", headers=H))
assert "complexity_score" in cost and "risk_level" in cost
print(f"迁移成本 ok: score={cost['complexity_score']}, risk={cost['risk_level']}")

ok("migrate to v2", client.post(f"/api/templates/{tpl2['id']}/migrate", headers=H,
    json={"operated_by": "admin01"}))
cost2 = ok("estimate rollback v2", client.get(
    f"/api/templates/{tpl2['id']}/estimate-rollback?target_version=1", headers=H))
assert "complexity_score" in cost2
print(f"回滚成本 ok: score={cost2['complexity_score']}")

# ========== create execution + score ==========
exec1 = ok("create execution", client.post("/api/executions", headers=H, json={
    "template_id": tpl2["id"], "executor": "admin01", "batch_prefix": "BATCH-TEST",
}))
exec_id = exec1["id"]
items = exec1.get("execution_items") or exec1.get("items", [])
print(f"exec batch_no = {exec1['batch_no']}, {len(items)} 项")

score_req = {"items": [
    {"template_item_id": items[0]["template_item_id"], "score": 18,
     "result": "pass", "scored_by": "admin01"},
    {"template_item_id": items[1]["template_item_id"], "score": 30,
     "result": "pass", "scored_by": "admin01"},
    {"template_item_id": items[2]["template_item_id"], "score": 0,
     "result": "fail", "scored_by": "admin01", "remark": "接地异常"},
]}
ok("score execution", client.post(f"/api/executions/{exec_id}/score", headers=H, json=score_req))

# ========== Feature 1: ScoreRevision 回放 ==========
print("\n[Feature 1] ScoreRevision 回放")
rev_req = {
    "items": [{
        "template_item_id": items[0]["template_item_id"],
        "score": 15, "max_score": 20, "result": "pass",
        "scored_by": "admin01", "remark": "颜色扣3分"
    }],
    "changed_by": "admin01",
    "reason": "复核修正打分",
}
modify = ok("modify score", client.post(
    f"/api/executions/{exec_id}/score-modify", headers=H, json=rev_req))

revs = ok("list score revisions", client.get(
    f"/api/executions/{exec_id}/score-revisions", headers=H))
assert len(revs) >= 1
print(f"Score 修订数: {len(revs)}")

if revs:
    rep = ok("score-replay", client.post(
        f"/api/executions/{exec_id}/score-replay", headers=H,
        json={"revision_ids": [revs[0]["id"]],
              "operated_by": "admin01", "reason": "测试回放"}))
    print("Score 回放 ok")

# ========== Feature 3: executions 异常流转 ==========
print("\n[Feature 3] executions 异常流转")
ok("suspend execution", client.post(f"/api/executions/{exec_id}/suspend", headers=H,
    json={"operated_by": "admin01", "reason": "设备故障"}))
e = ok("get suspended execution", client.get(f"/api/executions/{exec_id}", headers=H))
assert e["status"] == "suspended", f"expect suspended, got {e['status']}"

ok("resume execution", client.post(f"/api/executions/{exec_id}/resume", headers=H))
e = ok("get resumed execution", client.get(f"/api/executions/{exec_id}", headers=H))
assert e["status"] == "in_progress"
print("暂停/恢复 ok")

# ========== Feature 4: NC 升级阈值 ==========
print("\n[Feature 4] NC 升级阈值")
nc_rule = ok("create escalation rule", client.post("/api/executions/escalation-rules",
    headers=H, json={
        "rule_name": "minor逾期自动升级major", "trigger_type": "overdue_days",
        "from_severity": "minor", "trigger_value": 1,
        "target_severity": "major", "notify_roles": "qa_manager", "is_active": True,
        "description": "minor NC 1天未整改自动升级"
    }))
assert nc_rule["id"] > 0

# 创建 NC
nc = ok("create nc", client.post("/api/executions/nonconformances", headers=H, json={
    "execution_item_id": items[2]["id"],
    "description": "接地异常未解决", "severity": "minor", "disposition": "rework",
    "created_by": "admin01",
}))
nc_id = nc["id"]
print(f"NC id={nc_id}, severity={nc['severity']}")

# 手动升级 minor → major
escalated = ok("manual escalate nc minor→major", client.post(
    f"/api/executions/nonconformances/{nc_id}/escalate",
    headers=H, json={"escalated_by": "admin01", "reason": "安全隐患"}))
assert escalated["severity"] == "major"
print(f"NC 升级阈值 ok: severity now = {escalated['severity']}")
# 再升级 major → critical
escalated2 = ok("manual escalate nc major→critical", client.post(
    f"/api/executions/nonconformances/{escalated['id']}/escalate",
    headers=H, json={"escalated_by": "admin01", "reason": "持续恶化"}))
assert escalated2["severity"] == "critical"
nc_id = escalated2["id"]
print(f"NC 升级 ok: severity final = {escalated2['severity']}")

# ========== Feature 2: RectificationTransfer 审批 ==========
print("\n[Feature 2] RectificationTransfer 审批")
rct = ok("create rectification", client.post(
    f"/api/rectifications/{nc_id}", headers=H, json={
        "action_plan": "1. 更换接地线 2. 检查电路",
        "responsible_person": "inspector01",
        "due_date": "2025-12-31T23:59:59",
        "remark": "紧急整改",
    }))
rct_id = rct["id"]

# inspector01 申请转移给 admin01
transfer = ok("inspector transfer-request", client.post(
    f"/api/rectifications/{rct_id}/transfer-request",
    headers=H2, json={
        "to_person": "admin01", "reason": "工作安排调整",
        "requested_by": "inspector01",
    }))
assert transfer["status"] == "pending"
print(f"转移申请 ok, id={transfer['id']}, status={transfer['status']}")

# admin 批准
approved = ok("admin approve transfer", client.post(
    f"/api/rectifications/{rct_id}/transfer-approve",
    headers=H, json={
        "approver": "admin01", "decision": "approved", "comment": "同意调整"
    }))
rct_after = ok("get rectification after transfer",
             client.get(f"/api/rectifications/{rct_id}", headers=H))
assert rct_after["responsible_person"] == "admin01"
print("整改单转移审批 ok")

# ========== Feature 5: 仲裁终态共识 ==========
print("\n[Feature 5] 仲裁终态共识")
ok("complete execution", client.post(f"/api/executions/{exec_id}/complete", headers=H))

ok("review 1 approved", client.post(f"/api/reviews/{exec_id}", headers=H, json={
    "reviewer": "admin01", "result": "approved", "comment": "合格"
}))
ok("review 2 rejected", client.post(f"/api/reviews/{exec_id}", headers=H2, json={
    "reviewer": "inspector01", "result": "rejected", "comment": "不通过"
}))

ok("consensus vote 1 approved", client.post(
    f"/api/reviews/{exec_id}/consensus-vote", headers=H,
    json={"voter": "admin01", "vote": "approved", "comment": "可以通过"}))
ok("consensus vote 2 rejected", client.post(
    f"/api/reviews/{exec_id}/consensus-vote", headers=H2,
    json={"voter": "inspector01", "vote": "rejected", "comment": "不通过"}))

consensus = ok("check consensus", client.post(
    f"/api/reviews/{exec_id}/consensus-check", headers=H,
    json={"min_voters": 2, "threshold_ratio": 0.6, "final_decision_maker": "admin01"}))
print(f"共识状态: reached={consensus.get('reached_consensus')}, "
      f"ratio_approved={consensus.get('ratio_approved')}")

# 终态决策
final = ok("finalize consensus by decision maker", client.post(
    f"/api/reviews/{exec_id}/consensus-finalize", headers=H,
    json={"arbitrator": "admin01", "result": "approved", "comment": "终裁通过"}))
print("仲裁共识 ok")

# ========== Feature 6: RBAC 矩阵 ==========
print("\n[Feature 6] RBAC 矩阵")
rbac = ok("list rbac entries", client.get("/api/users/rbac", headers=H))
assert len(rbac) > 0

matrix = ok("get rbac grouped matrix", client.get("/api/users/rbac/matrix", headers=H))
roles = [m["role"] for m in matrix]
assert "admin" in roles and "qa_manager" in roles and "inspector" in roles and "viewer" in roles
print(f"RBAC 矩阵 ok: {len(matrix)} roles")

check = ok("check rbac permission", client.get(
    "/api/users/rbac/check?resource=execution&action=create", headers=H))
assert check["allowed"] is True
print(f"RBAC 检查 ok: admin allowed={check['allowed']}")

custom = ok("create custom rbac", client.post("/api/users/rbac", headers=H, json={
    "role": "inspector", "resource": "report", "action": "export",
    "description": "导出质检报告"
}))
assert custom["id"] > 0
print("自定义 RBAC ok")

# ========== Feature 8: 审计日志聚合查询 + 索引 ==========
print("\n[Feature 8] 审计日志聚合查询")
logs = ok("list audit logs", client.get(
    "/api/users/audit-logs/list?limit=10", headers=H))
assert isinstance(logs, list)
agg = ok("aggregate audit logs", client.get(
    "/api/users/audit-logs/aggregate?group_by=date,action&limit=20", headers=H))
assert isinstance(agg, list)
print(f"审计日志: list={len(logs)} 条, agg={len(agg)} 组")

# ---------- all done ----------
print("\n" + "=" * 60)
print("ALL 8 NEW FEATURES TEST PASSED")
print("=" * 60)
