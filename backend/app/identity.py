"""信号电源操作身份与权限：按所属车站划定范围，按角色授予权限。

身份不靠前端自报姓名，而是由前端在请求头 X-Operator-Id 携带工号，
服务端在身份目录里核对归属车站、角色与当班状态，确保切换记录里的经手人可追溯。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Header

from app.errors import DomainError
from app.store import store

USERS_TABLE = "identity_users"

# --- 权限点：越权提示里直接用这些名字说明缺的是哪个权限 ---
PERM_VIEW = "电源屏查看"
PERM_REGISTER_FLUCTUATION = "波动登记"
PERM_SWITCH_BACKUP = "备用电源切换"
PERM_HANDLE_FAULT = "故障处理"
PERM_EDIT_CONFIG = "模块配置修改"

# 仅查看权限：查看人员只能看，不能动任何模块配置/状态。
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "查看人员": [PERM_VIEW],
    "值班员": [
        PERM_VIEW,
        PERM_REGISTER_FLUCTUATION,
        PERM_SWITCH_BACKUP,
        PERM_HANDLE_FAULT,  # 还要满足「当班」，见 require_fault_handler
    ],
    "电源管理员": [
        PERM_VIEW,
        PERM_REGISTER_FLUCTUATION,
        PERM_SWITCH_BACKUP,
        PERM_HANDLE_FAULT,
        PERM_EDIT_CONFIG,
    ],
}


@dataclass(frozen=True)
class Operator:
    """通过请求头解析出的当前操作人。"""

    工号: str
    姓名: str
    所属车站: str
    角色: str
    当班: bool

    @property
    def permissions(self) -> list[str]:
        return ROLE_PERMISSIONS.get(self.角色, [])

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    @property
    def on_duty(self) -> bool:
        return bool(self.当班)


def list_operators() -> list[dict[str, Any]]:
    """身份目录：前端切换当前操作人时使用。"""
    return [dict(row) for row in store.rows(USERS_TABLE)]


def get_operator(operator_id: str | None) -> Operator:
    """按工号解析当前操作人；没有携带身份时按未登录处理。"""
    code = (operator_id or "").strip()
    if not code:
        raise DomainError(
            "未识别到操作人身份，请先在右上角选择当前值班人员后再操作",
            status_code=401,
        )
    row = next(
        (row for row in store.rows(USERS_TABLE) if str(row.get("工号")) == code),
        None,
    )
    if row is None:
        raise DomainError(f"工号 {code} 不在信号电源操作身份目录中", status_code=401)
    return Operator(
        工号=str(row["工号"]),
        姓名=str(row["姓名"]),
        所属车站=str(row["所属车站"]),
        角色=str(row["角色"]),
        当班=bool(row.get("当班", False)),
    )


def require_operator(x_operator_id: str | None = Header(default=None)) -> Operator:
    """FastAPI 依赖：写操作必须携带可识别的操作人工号。"""
    return get_operator(x_operator_id)


def ensure_station_scope(operator: Operator, entry: dict[str, Any]) -> None:
    """按所属车站划定可操作范围：只能操作本车站的电源屏。"""
    target_station = str(entry.get("所属车站") or "")
    if target_station != operator.所属车站:
        raise DomainError(
            f"越权操作：{operator.姓名}（{operator.所属车站}）不能操作"
            f"{target_station}的电源屏 {entry.get('电源屏编号')}，仅可操作本车站设备",
            status_code=403,
        )


def ensure_permission(operator: Operator, permission: str) -> None:
    """权限点校验：拦下时明确说明缺的是哪个权限。"""
    if not operator.has(permission):
        raise DomainError(
            f"越权操作：{operator.角色}「{operator.姓名}」缺少「{permission}」权限，"
            f"该操作已被拦截",
            status_code=403,
            missing_permission=permission,
        )


def ensure_on_duty(operator: Operator, action_label: str) -> None:
    """故障处置类操作只能由当班人员执行。"""
    if not operator.on_duty:
        raise DomainError(
            f"越权操作：{action_label}只能由当班人员执行，"
            f"{operator.姓名}当前为非当班状态，操作已被拦截",
            status_code=403,
            missing_permission="当班操作",
        )


def ensure_enabled(entry: dict[str, Any]) -> None:
    """已停用的电源屏不允许再被改动。"""
    if not entry.get("enabled", True):
        raise DomainError(
            f"电源屏 {entry.get('电源屏编号')} 已停用并封存，任何状态切换与配置改动均被禁止",
            status_code=403,
        )
