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

# ============================================================
# 第二轮 8 个 Feature
# ============================================================
print("\n\n" + ">" * 60)
print(">>>>>>>> 第二轮 8 Feature 测试 <<<<<<<<")
print(">" * 60)

# ---------- [Feature 1] ScoreRevision 回放并发隔离 ----------
print("\n[第二轮 Feature 1] ScoreRevision 回放并发隔离")
revs2 = ok("list revisions", client.get(
    f"/api/executions/{exec1['id']}/score-revisions", headers=H))
rev_ids = [r["id"] for r in revs2[:2]]
lock = ok("acquire replay lock", client.post(
    f"/api/executions/{exec1['id']}/replay-lock",
    json={"revision_ids": rev_ids, "held_by": "admin01", "ttl_seconds": 300},
    headers=H))
print(f"回放锁 token={lock['replay_token']}, status={lock['status']}")
r_conflict = client.post(
    f"/api/executions/{exec1['id']}/replay-lock",
    json={"revision_ids": rev_ids, "held_by": "inspector01", "ttl_seconds": 300},
    headers=H)
print(f"并发抢占 status={r_conflict.status_code} (expected 409)")
assert r_conflict.status_code == 409
release = ok("release replay lock", client.post(
    f"/api/executions/{exec1['id']}/replay-lock/{lock['replay_token']}/release",
    headers=H))
print(f"释放锁 ok, status={release['status']}")

# ---------- [Feature 2] RectificationTransfer 多级签字审批链 ----------
print("\n[第二轮 Feature 2] RectificationTransfer 多级签字")
t_req = ok("request transfer v2", client.post(
    f"/api/rectifications/{rct_id}/transfer-request",
    json={"to_person": "inspector02", "reason": "出差委托", "requested_by": "inspector01"},
    headers=H))
print(f"转移申请 id={t_req['id']}")
chain = ok("create serial approval chain", client.post(
    f"/api/rectifications/{rct_id}/transfer-chain",
    json={"transfer_id": t_req["id"], "approvers": ["qa_manager01", "qa_manager02"], "mode": "serial"},
    headers=H))
print(f"审批链: {len(chain)} 步, approvers={[s['approver'] for s in chain]}")
# 第一步审批
step1 = ok("approve step 1", client.post(
    f"/api/rectifications/{rct_id}/transfer-chain/{t_req['id']}/approve",
    json={"approver": "qa_manager01", "decision": "approved", "comment": "同意第一步"},
    headers=H))
print(f"step1 ok: decision={step1['decision']}")
# 非当前审批人不能批
r_wrong = client.post(
    f"/api/rectifications/{rct_id}/transfer-chain/{t_req['id']}/approve",
    json={"approver": "qa_manager01", "decision": "approved"},
    headers=H)
print(f"非当前审批人 status={r_wrong.status_code} (expected 403)")
# 第二步审批
step2 = ok("approve step 2 (serial final)", client.post(
    f"/api/rectifications/{rct_id}/transfer-chain/{t_req['id']}/approve",
    json={"approver": "qa_manager02", "decision": "approved", "comment": "同意第二步"},
    headers=H))
print(f"多级串行审批 ok, 最终 decision={step2['decision']}")
steps_final = ok("list chain steps", client.get(
    f"/api/rectifications/{rct_id}/transfer-chain/{t_req['id']}",
    headers=H))
assert all(s["decision"] == "approved" for s in steps_final)

# ---------- [第二轮 Feature 3] executions 异常流转死信清理 ----------
print("\n[第二轮 Feature 3] executions 异常流转死信清理")
# 新建一个执行记录，然后取消
exec_dl = ok("create execution for dead letter", client.post(
    "/api/executions", headers=H, json={
        "template_id": tpl2["id"], "executor": "admin01", "batch_prefix": "DL-TEST",
    }))
r_cancel = ok("cancel execution for DL", client.post(
    f"/api/executions/{exec_dl['id']}/cancel", headers=H))
print(f"取消 status={r_cancel['status']}")
dl = ok("archive dead letter", client.post(
    "/api/executions/dead-letter/archive",
    json={"reason": "长期挂起清理", "execution_ids": [r_cancel["id"]]},
    headers=H))
print(f"死信归档 ok: {len(dl)} 条, batch_no={dl[0]['batch_no']}")
dl_list = ok("list dead letter archives", client.get(
    "/api/executions/dead-letter/list?limit=10", headers=H))
print(f"死信列表: {len(dl_list)} 条")

# ---------- [第二轮 Feature 4] NC 升级阈值动态调优 ----------
print("\n[第二轮 Feature 4] NC 升级阈值动态调优")
tuning = ok("analyze nc threshold", client.post(
    "/api/executions/nc-threshold/analyze",
    json={"severity": "minor", "trigger_type": "recurring_count", "window_days": 30, "apply_recommendation": False},
    headers=H))
print(f"阈值调优 ok: current={tuning['current_value']}, "
      f"recommended={tuning['recommended_value']}, "
      f"confidence={tuning['confidence']}, sample={tuning['sample_size']}")
tuning_hist = ok("list tuning history", client.get(
    "/api/executions/nc-threshold/history?limit=10", headers=H))
print(f"阈值调优历史: {len(tuning_hist)} 条")

# ---------- [第二轮 Feature 5] 版本回滚迁移成本分批策略 ----------
print("\n[第二轮 Feature 5] 版本迁移分批策略")
# 创建第二条执行记录（用模板 v2）
pl_id = pl["id"]
tpl1_id = tpl["id"]   # v1
tpl2_id = tpl2["id"]  # v2
exec2 = ok("create second execution for batch migration", client.post(
    "/api/executions",
    json={"template_id": tpl2_id, "product_line_id": pl_id, "executor": "inspector01", "batch_prefix": "QA"},
    headers=H2))
# 建一个反向迁移任务 (v2 -> v1)
mb = ok("create migration batch", client.post(
    "/api/templates/migration-batches",
    params={"created_by": "admin01"},
    json={"from_template_id": tpl2_id, "to_template_id": tpl1_id,
          "strategy": "time_window", "batch_size": 10},
    headers=H))
print(f"分批任务 id={mb['id']}, total_target={mb['total_target']}, status={mb['status']}")
mb_run = ok("run migration batch next", client.post(
    f"/api/templates/migration-batches/{mb['id']}/run-next",
    headers=H))
print(f"执行分批 ok: processed={mb_run['total_processed']}, failed={mb_run['total_failed']}, status={mb_run['status']}")
mb_list = ok("list migration batches", client.get(
    "/api/templates/migration-batches?limit=10", headers=H))
print(f"分批任务列表: {len(mb_list)} 条")

# ---------- [第二轮 Feature 6] RBAC 矩阵运行时切换（Profile） ----------
print("\n[第二轮 Feature 6] RBAC 矩阵运行时切换")
profile = ok("create rbac profile", client.post(
    "/api/users/rbac/profiles",
    json={
        "name": "strict-security",
        "description": "严格安全模式",
        "entries": [
            {"role": "admin", "resource": "*", "action": "*", "description": "admin 全部权限"},
            {"role": "inspector", "resource": "execution", "action": "read", "description": "只读"},
        ],
    },
    headers=H))
print(f"Profile id={profile['id']}, name={profile['name']}")
profiles = ok("list rbac profiles", client.get(
    "/api/users/rbac/profiles", headers=H))
print(f"Profile 列表: {len(profiles)} 个")
activated = ok("activate rbac profile", client.post(
    f"/api/users/rbac/profiles/{profile['id']}/activate",
    headers=H))
print(f"激活 Profile ok: is_active={activated['is_active']}")
matrix_after = ok("check matrix after activate", client.get(
    "/api/users/rbac/matrix", headers=H))
print(f"激活后角色数: {len(matrix_after)}")

# ---------- [第二轮 Feature 7] log 记录查询索引优化 ----------
print("\n[第二轮 Feature 7] log 记录查询索引优化")
stats = ok("capture index stats", client.post(
    "/api/users/index-stats/capture",
    json={"sample_queries": None},
    headers=H))
print(f"索引统计样本: {len(stats)} 个")
for s in stats:
    marker = "✓" if s["idx_scan"] > 0 else "✗"
    print(f"  {marker} {s['index_name']}: idx_scan={s['idx_scan']}, seq={s['seq_scan']}")
summary = ok("index summary", client.get(
    "/api/users/index-stats/summary", headers=H))
print(f"索引命中率: {summary['hit_ratio']*100:.1f}% "
      f"(hit={summary['index_hit_samples']}, miss={summary['index_miss_samples']})")

# ---------- all done round 2 ----------
print("\n" + "=" * 60)
print("ALL ROUND-2 FEATURES TEST PASSED")
print("=" * 60)

# ---------- all done ----------
print("\n" + "=" * 60)
print("ALL 8 NEW FEATURES TEST PASSED")
print("=" * 60)
