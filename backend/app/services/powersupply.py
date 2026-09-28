"""信号电源业务规则：权限归属、状态流转、操作记录与幂等都收在这里。

权限口径：
- 按所属车站划定可操作范围，越站操作直接拦下；
- 越权操作返回缺失的具体权限点；
- 处理故障只能由当班人员执行；
- 只有查看权限的人不能改动模块配置；
- 已停用电源屏禁止任何改动。

一致性口径：
- 每次生效的操作写一条操作记录（台账），电源屏列表的「最近操作人」与
  记录详情的「经手人」取自同一条记录，天然一致；
- 同一电源屏同一动作串行化 + 请求标识去重，重复操作只生效一次。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.errors import DomainError
from app.identity import (
    PERM_EDIT_CONFIG,
    PERM_HANDLE_FAULT,
    PERM_REGISTER_FLUCTUATION,
    PERM_SWITCH_BACKUP,
    Operator,
    ensure_enabled,
    ensure_on_duty,
    ensure_permission,
    ensure_station_scope,
)
from app.store import store

MODULE = "powersupply"
RECORDS_MODULE = "powersupply_records"
REQUIRED_FIELDS = ["电源屏编号", "所属车站", "输入电压"]

STATUS_NORMAL = "供电正常"
STATUS_FLUCTUATION = "电压波动"
STATUS_FAULT = "模块故障"
STATUS_BACKUP = "备用供电"
STATUS_DISABLED = "已停用"

# 动作 -> (所需权限, 允许的来源状态集合, 目标状态)。
# 来源状态即重复操作的第一道闸：当前状态不在来源集合里，说明这一步已经做过。
ACTION_RULES: dict[str, dict[str, Any]] = {
    "登记波动": {
        "permission": PERM_REGISTER_FLUCTUATION,
        "from": {STATUS_NORMAL},
        "to": STATUS_FLUCTUATION,
    },
    "切换备用": {
        "permission": PERM_SWITCH_BACKUP,
        "from": {STATUS_FLUCTUATION, STATUS_FAULT},
        "to": STATUS_BACKUP,
    },
    "处理故障": {
        "permission": PERM_HANDLE_FAULT,
        "from": {STATUS_FLUCTUATION, STATUS_FAULT, STATUS_BACKUP},
        "to": STATUS_NORMAL,
        "on_duty_only": True,
    },
}

CONFIG_FIELDS = ["输入电压", "模块配置"]

# 每个电源屏一把锁：同一屏的动作串行执行，避免两路并发都读到旧状态、双双报成功。
_locks_guard = threading.Lock()
_locks: dict[int, threading.Lock] = {}


def _lock_for(entry_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(entry_id, threading.Lock())


class PowersupplyService:
    # ---------------- 列表 / 明细 ----------------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        station: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("电源屏编号", ""))]
        if station:
            rows = [row for row in rows if row.get("所属车站") == station]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---------------- 操作记录（台账） ----------------
    def list_records(
        self,
        *,
        entry_id: int | None = None,
        station: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(RECORDS_MODULE)
        if entry_id is not None:
            entry = self.get_entry(entry_id)
            panel_no = str(entry.get("电源屏编号")) if entry else None
            rows = [row for row in rows if panel_no and row.get("电源屏编号") == panel_no]
        if station:
            rows = [row for row in rows if row.get("所属车站") == station]
        rows = sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_record(self, record_id: int) -> dict[str, Any] | None:
        return store.find(RECORDS_MODULE, record_id)

    # ---------------- 动作 ----------------
    def run_action(
        self,
        entry_id: int,
        action: str,
        operator: Operator,
        *,
        request_id: str | None = None,
        remark: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """对电源屏执行动作，返回 (电源屏, 操作记录)。

        重复操作不返回旧记录，而是直接抛 409；权限、归属、当班、停用、状态机、
        幂等六道闸全部在这里收口。
        """
        entry = self.get_entry(entry_id)
        if entry is None:
            raise DomainError(f"电源屏 {entry_id} 不存在或已归档", status_code=404)
        if action not in ACTION_RULES:
            raise DomainError(f"动作「{action}」不属于信号电源可执行范围")

        rule = ACTION_RULES[action]
        # 1) 权限点：先说明缺的是哪个权限
        ensure_permission(operator, rule["permission"])
        # 2) 归属车站范围：再校验是否越站操作
        ensure_station_scope(operator, entry)
        # 3) 当班要求（处理故障只能由当班人员执行）
        if rule.get("on_duty_only"):
            ensure_on_duty(operator, action)
        # 4) 停用屏禁止改动
        ensure_enabled(entry)

        lock = _lock_for(entry_id)
        with lock:
            current = str(entry.get("status"))
            # 5) 状态机：当前状态不在该动作的来源状态集合里，说明这一步已经做过，
            #    重复操作直接拦下，只生效第一次（并发时后到的一路在此被挡住）。
            if current not in rule["from"]:
                raise DomainError(
                    f"「{action}」重复提交：电源屏当前为「{current}」，"
                    f"该动作此前已生效，本次不再重复执行",
                    status_code=409,
                    duplicate=True,
                )

            # 6) 请求标识幂等：同一请求标识只认第一次
            if request_id:
                existing = self._find_by_request_id(entry, request_id)
                if existing is not None:
                    raise DomainError(
                        f"请求标识 {request_id} 已处理过，重复操作只生效一次",
                        status_code=409,
                        duplicate=True,
                    )

            before = current
            after = rule["to"]
            record = self._write_record(
                entry=entry,
                action=action,
                before=before,
                after=after,
                operator=operator,
                request_id=request_id,
                remark=remark,
            )
            entry["status"] = after
            entry["电源状态"] = after
            entry["pending"] = after not in {STATUS_NORMAL, STATUS_BACKUP}
            entry["abnormal"] = after in {STATUS_FLUCTUATION, STATUS_FAULT}
            self._sync_last_operator(entry, record)
            return entry, record

    def update_config(
        self,
        entry_id: int,
        values: dict[str, Any],
        operator: Operator,
        *,
        request_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """修改输入电压 / 模块配置：需要模块配置修改权限，且不能动停用屏。"""
        entry = self.get_entry(entry_id)
        if entry is None:
            raise DomainError(f"电源屏 {entry_id} 不存在或已归档", status_code=404)

        ensure_permission(operator, PERM_EDIT_CONFIG)
        ensure_station_scope(operator, entry)
        ensure_enabled(entry)

        # 先做格式校验（不允许置空），真正的差异比对放到锁内，避免两路并发
        # 拿着相同值都通过「有变化」判断、各写一条记录。
        proposed: dict[str, str] = {}
        for field in CONFIG_FIELDS:
            new_value = values.get(field)
            if new_value is None:
                continue
            new_value = str(new_value).strip()
            if not new_value:
                raise DomainError(f"「{field}」不允许置空")
            proposed[field] = new_value

        with _lock_for(entry_id):
            if request_id and self._find_by_request_id(entry, request_id) is not None:
                raise DomainError(
                    f"请求标识 {request_id} 已处理过，重复提交只生效一次",
                    status_code=409,
                    duplicate=True,
                )
            changes = {
                field: value
                for field, value in proposed.items()
                if str(entry.get(field) or "") != value
            }
            if not changes:
                raise DomainError("模块配置没有变化，无需提交", status_code=409, duplicate=True)
            before = str(entry.get("status"))
            for field, value in changes.items():
                entry[field] = value
            detail = "；".join(f"{name}改为{value}" for name, value in changes.items())
            record = self._write_record(
                entry=entry,
                action="修改模块配置",
                before=before,
                after=before,
                operator=operator,
                request_id=request_id,
                remark=detail,
            )
            self._sync_last_operator(entry, record)
        return entry, record

    # ---------------- 内部工具 ----------------
    def _write_record(
        self,
        *,
        entry: dict[str, Any],
        action: str,
        before: str,
        after: str,
        operator: Operator,
        request_id: str | None,
        remark: str | None,
    ) -> dict[str, Any]:
        rows = store.rows(RECORDS_MODULE)
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        record = {
            "id": next_id,
            "记录号": f"PS-LOG-{next_id:04d}",
            "电源屏编号": entry.get("电源屏编号"),
            "所属车站": entry.get("所属车站"),
            "动作": action,
            "操作前状态": before,
            "操作后状态": after,
            "经手人": operator.姓名,
            "经手人工号": operator.工号,
            "操作时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "结果": "生效",
            "请求标识": request_id or f"auto-{next_id}",
            "备注": (remark or "").strip(),
        }
        rows.append(record)
        return record

    @staticmethod
    def _sync_last_operator(entry: dict[str, Any], record: dict[str, Any]) -> None:
        """台账列与记录详情共用同一份经手人数据，刷新后仍然保留。"""
        entry["最近操作人"] = record["经手人"]
        entry["最近动作"] = record["动作"]
        entry["最近记录号"] = record["记录号"]
        entry["最近操作时间"] = record["操作时间"]

    @staticmethod
    def _find_by_request_id(entry: dict[str, Any], request_id: str) -> dict[str, Any] | None:
        panel_no = entry.get("电源屏编号")
        for row in store.rows(RECORDS_MODULE):
            if row.get("电源屏编号") == panel_no and row.get("请求标识") == request_id:
                return row
        return None
