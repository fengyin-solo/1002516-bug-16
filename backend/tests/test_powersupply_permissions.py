"""信号电源权限、归属、当班、停用与幂等的回归测试。

用 TestClient + 内存 store 跑，每个用例拿到的是 seed 初始化后的干净数据：
store 在模块导入时从 SEED_ROWS 构建，测试里通过重置两张电源表来隔离。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import SEED_ROWS
from app.store import store
from app.services import powersupply as ps_service

client = TestClient(app)

# 工号 -> 角色/车站/当班，见 seed.py 的 identity_users
OP_JZ = "OP-JZ-01"   # 周建平 江洲站 值班员 当班
VIEW_JZ = "OP-JZ-02"  # 陈立群 江洲站 查看人员 当班
OP_NQ = "OP-NQ-01"   # 林晓燕 宁桥站 值班员 当班
OP_OFF = "OP-JZ-03"  # 宋望 江洲站 值班员 非当班
ADM_JZ = "SV-JZ-01"  # 高志远 江洲站 电源管理员 当班
ADM_NQ = "SV-NQ-01"  # 赵清扬 宁桥站 电源管理员 非当班


@pytest.fixture(autouse=True)
def reset_powersupply_tables():
    """每个用例前把电源屏与台账还原成 seed，避免相互污染。"""
    store._tables[ps_service.MODULE] = [dict(r) for r in SEED_ROWS[ps_service.MODULE]]
    store._tables[ps_service.RECORDS_MODULE] = [
        dict(r) for r in SEED_ROWS[ps_service.RECORDS_MODULE]
    ]
    yield


def _action(entry_id: int, action: str, operator: str | None, request_id: str | None = None):
    headers = {"X-Operator-Id": operator} if operator else {}
    values: dict[str, object] = {"action": action}
    if request_id:
        values["request_id"] = request_id
    return client.post(
        f"/api/powersupply/{entry_id}/actions",
        headers=headers,
        json={"values": values},
    )


# ---------------- 身份与权限 ----------------
def test_without_identity_is_401():
    res = _action(2, "切换备用", None)
    assert res.status_code == 401


def test_viewer_cannot_switch_backup():
    res = _action(2, "切换备用", VIEW_JZ)
    assert res.status_code == 403
    assert res.json()["detail"]["missing_permission"] == "备用电源切换"


def test_viewer_cannot_edit_config():
    res = client.put(
        "/api/powersupply/1/config",
        headers={"X-Operator-Id": VIEW_JZ},
        json={"values": {"输入电压": "AC 999V"}},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["missing_permission"] == "模块配置修改"


def test_cross_station_operator_blocked():
    # 宁桥站值班员不能动江洲站的屏（两边都有切换权限，差异只在车站）
    res = _action(1, "登记波动", OP_NQ)
    assert res.status_code == 403
    assert "不能操作江洲站" in res.json()["detail"]["message"]


def test_cross_station_admin_cannot_change_voltage():
    res = client.put(
        "/api/powersupply/1/config",
        headers={"X-Operator-Id": ADM_NQ},
        json={"values": {"输入电压": "AC 999V"}},
    )
    assert res.status_code == 403
    assert "不能操作江洲站" in res.json()["detail"]["message"]


def test_off_duty_cannot_handle_fault():
    # 宋望是江洲站值班员（有处理故障权限）但非当班
    res = _action(2, "处理故障", OP_OFF)
    assert res.status_code == 403
    assert res.json()["detail"]["missing_permission"] == "当班操作"


def test_on_duty_can_handle_fault():
    res = _action(2, "处理故障", OP_JZ)
    assert res.status_code == 200
    assert res.json()["entry"]["状态"] == "供电正常"


def test_disabled_panel_cannot_be_changed():
    res = _action(5, "登记波动", OP_JZ)
    assert res.status_code == 403
    assert "已停用" in res.json()["detail"]["message"]
    res2 = client.put(
        "/api/powersupply/5/config",
        headers={"X-Operator-Id": ADM_JZ},
        json={"values": {"输入电压": "AC 999V"}},
    )
    assert res2.status_code == 403


# ---------------- 幂等与并发 ----------------
def test_duplicate_switch_only_applies_once():
    first = _action(3, "切换备用", OP_NQ, request_id="k-1")
    second = _action(3, "切换备用", OP_NQ, request_id="k-2")
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["duplicate"] is True
    # 台账里这台屏的「切换备用」生效记录只有一条
    records = client.get("/api/powersupply/records?entry_id=3").json()["items"]
    switch = [r for r in records if r["动作"] == "切换备用" and r["结果"] == "生效"]
    assert len(switch) == 1


def test_same_request_id_replay_is_idempotent():
    first = _action(2, "切换备用", OP_JZ, request_id="same-key")
    assert first.status_code == 200
    # 屏已到备用供电；带相同键再发，仍然 409 且不新增记录
    replay = _action(2, "切换备用", OP_JZ, request_id="same-key")
    assert replay.status_code == 409


def test_concurrent_switches_only_one_wins():
    import concurrent.futures

    def call(key: str):
        return _action(3, "切换备用", OP_NQ, request_id=key).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(call, ["c1", "c2"]))
    assert sorted(codes) == [200, 409]


# ---------------- 经手人一致性 / 保留 ----------------
def test_list_operator_matches_record_detail():
    res = _action(3, "切换备用", OP_NQ)
    assert res.status_code == 200
    entry = client.get("/api/powersupply/3").json()
    record_no = entry["最近记录号"]
    records = client.get("/api/powersupply/records?entry_id=3").json()["items"]
    record = next(r for r in records if r["记录号"] == record_no)
    detail = client.get(f"/api/powersupply/records/{record['id']}").json()
    assert entry["最近操作人"] == detail["经手人"] == "林晓燕"
    assert detail["记录号"] == record_no


def test_operator_persists_after_list_refresh():
    _action(2, "切换备用", OP_JZ)
    # 再次拉列表（模拟刷新），最近操作人仍在
    items = client.get("/api/powersupply?station=江洲站").json()["items"]
    row = next(i for i in items if i["电源屏编号"] == "PDY-JZ-02")
    assert row["最近操作人"] == "周建平"
    assert row["状态"] == "备用供电"


# ---------------- 配置修改 ----------------
def test_admin_can_edit_own_station_config():
    res = client.put(
        "/api/powersupply/1/config",
        headers={"X-Operator-Id": ADM_JZ},
        json={"values": {"输入电压": "AC 390V", "模块配置": "新配置"}},
    )
    assert res.status_code == 200
    assert res.json()["entry"]["输入电压"] == "AC 390V"
    assert res.json()["entry"]["最近操作人"] == "高志远"


def test_operator_cannot_edit_config():
    res = client.put(
        "/api/powersupply/1/config",
        headers={"X-Operator-Id": OP_JZ},
        json={"values": {"输入电压": "AC 390V"}},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["missing_permission"] == "模块配置修改"
