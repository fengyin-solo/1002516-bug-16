"""信号电源业务规则：状态流转、字段校验、权限收口与操作台账都在这里。"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.services import powersupply_auth as auth
from app.store import store

MODULE = "powersupply"
REQUIRED_FIELDS = ["电源屏编号", "所属车站", "输入电压"]
STATUS_ORDER = ["供电正常", "电压波动", "模块故障", "备用供电"]
# 动作 -> 执行后电源屏所处状态
ACTION_RULES = {"登记波动": "电压波动", "切换备用": "备用供电", "处理故障": "供电正常"}
NEGATIVE_ACTIONS: list[str] = []

# 配置字段：只有具备「模块配置修改权限」且车站归属匹配的人能改
CONFIG_FIELDS = ["输入电压", "模块配置"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class PowersupplyService:
    def __init__(self) -> None:
        # 同一路备用电源两边同时切换时，靠这把锁串行化，保证重复请求只生效一次
        self._lock = threading.RLock()

    def list_entries(
        self,
        *,
        operator: dict[str, Any] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("电源屏编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = rows[start:start + size]
        # 列表不带完整台账，只给出可判定的字段；并按当前操作人逐行动作授权
        return [self._list_view(row, operator) for row in page_rows], total

    def _list_view(self, row: dict[str, Any], operator: dict[str, Any] | None) -> dict[str, Any]:
        view = {key: value for key, value in row.items() if key != "操作记录"}
        actions: list[dict[str, Any]] = []
        for action in ACTION_RULES:
            allowed, reason = self._check(operator or auth.get_operator(None), action, row)
            actions.append({"动作": action, "允许": allowed, "拦截原因": reason})
        view["可执行动作"] = actions
        return view

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(
        self,
        values: dict[str, Any],
        operator: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[str], str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, ""
        station = str(values.get("所属车站") or "").strip()
        # 登记电源屏属于配置变更，同样要卡权限和车站归属
        allowed, reason = auth.evaluate(
            operator, "修改配置", {"所属车站": station, "启用状态": "启用"}
        )
        if not allowed:
            return None, [], reason
        with self._lock:
            rows = store.rows(MODULE)
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
            for field in ["输出电压", "输出电流", "模块配置", "切换装置", "电源状态"]:
                if values.get(field):
                    entry[field] = values[field]
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            entry["启用状态"] = "启用"
            entry["经手人"] = operator["姓名"]
            entry["操作记录"] = [
                self._record(operator["姓名"], "登记电源屏", f"在{station}登记电源屏")
            ]
            rows.append(entry)
        return entry, [], ""

    def run_action(
        self,
        entry_id: int,
        action: str,
        operator: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """执行动作。返回(记录, 提示信息, 是否实际生效)。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电源屏 {entry_id} 不存在或已归档", False
        allowed, reason = auth.evaluate(operator, action, entry)
        if not allowed:
            return None, reason, False

        target = ACTION_RULES[action]
        with self._lock:
            # 加锁后复查：两路请求切换同一路备用电源时，只有第一次生效
            if entry.get("status") == target:
                return None, f"电源屏已处于「{target}」，重复操作不会再次生效", False
            entry["status"] = target
            entry["pending"] = target != STATUS_ORDER[-1]
            entry["abnormal"] = action in NEGATIVE_ACTIONS
            entry["经手人"] = operator["姓名"]
            entry.setdefault("操作记录", []).append(
                self._record(operator["姓名"], action, f"状态变更为「{target}」")
            )
        return entry, f"电源屏已{action}，经手人：{operator['姓名']}", True

    def update_config(
        self,
        entry_id: int,
        values: dict[str, Any],
        operator: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电源屏 {entry_id} 不存在或已归档"
        allowed, reason = auth.evaluate(operator, "修改配置", entry)
        if not allowed:
            return None, reason
        changes = {
            field: str(values[field]).strip()
            for field in CONFIG_FIELDS
            if str(values.get(field) or "").strip()
        }
        if not changes:
            return None, "没有需要更新的配置项（输入电压、模块配置至少填一项）"
        with self._lock:
            detail = "、".join(f"{field}={value}" for field, value in changes.items())
            entry.update(changes)
            entry["经手人"] = operator["姓名"]
            entry.setdefault("操作记录", []).append(
                self._record(operator["姓名"], "修改配置", detail)
            )
        return entry, f"模块配置已更新，经手人：{operator['姓名']}"

    @staticmethod
    def _check(operator: dict[str, Any], action: str, entry: dict[str, Any]) -> tuple[bool, str]:
        allowed, reason = auth.evaluate(operator, action, entry)
        if allowed:
            target = ACTION_RULES[action]
            if entry.get("status") == target:
                return False, f"已处于「{target}」，无需重复{action}"
        return allowed, reason

    @staticmethod
    def _record(name: str, action: str, detail: str) -> dict[str, Any]:
        return {"时间": _now(), "经手人": name, "动作": action, "说明": detail}


service = PowersupplyService()
