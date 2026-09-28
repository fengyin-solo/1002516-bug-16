"""信号电源操作身份与权限规则。

按「所属车站」划定每个操作人的可操作范围；动作与权限点一一对应，
越权时返回缺少的具体权限，而不是笼统地拒绝。
"""
from __future__ import annotations

from typing import Any

# 动作（权限点）-> 中文权限名：拦截提示里直接引用
PERMISSION_LABELS: dict[str, str] = {
    "登记波动": "电源波动登记权限",
    "切换备用": "备用电源切换权限",
    "处理故障": "故障处理权限",
    "修改配置": "模块配置修改权限",
}

# 只有当班人员才能执行的动作
DUTY_REQUIRED_ACTIONS = {"处理故障"}

GLOBAL_SCOPE = "*"  # 车站范围为 * 表示可操作全线各站

# 值班名册：实际项目中来自账号体系；示例环境内置，保证开箱可演示
OPERATORS: list[dict[str, Any]] = [
    {
        "id": "zhangwei",
        "姓名": "张伟",
        "岗位": "江湾站值班员",
        "当班": True,
        "车站范围": ["江湾站"],
        "权限": ["登记波动", "切换备用", "处理故障"],
    },
    {
        "id": "lina",
        "姓名": "李娜",
        "岗位": "镇宁路站值班员",
        "当班": True,
        "车站范围": ["镇宁路站"],
        "权限": ["登记波动", "切换备用", "处理故障"],
    },
    {
        "id": "wangfang",
        "姓名": "王芳",
        "岗位": "江湾站学习值班员",
        "当班": False,
        "车站范围": ["江湾站"],
        "权限": ["登记波动", "切换备用", "处理故障"],
    },
    {
        "id": "zhaolei",
        "姓名": "赵磊",
        "岗位": "虹桥火车站值班员",
        "当班": True,
        "车站范围": ["虹桥火车站"],
        "权限": ["登记波动", "切换备用", "处理故障"],
    },
    {
        "id": "chenjun",
        "姓名": "陈军",
        "岗位": "信号电源调度（电源屏专责）",
        "当班": True,
        "车站范围": [GLOBAL_SCOPE],
        "权限": ["修改配置"],
    },
    {
        "id": "zhouqiang",
        "姓名": "周强",
        "岗位": "虹桥火车站电源屏配置专责",
        "当班": True,
        "车站范围": ["虹桥火车站"],
        "权限": ["修改配置"],
    },
    {
        "id": "sunjing",
        "姓名": "孙静",
        "岗位": "江湾站见习（只读账号）",
        "当班": True,
        "车站范围": ["江湾站"],
        "权限": [],
    },
]

_ANONYMOUS: dict[str, Any] = {
    "id": "",
    "姓名": "未登录访客",
    "岗位": "无岗位",
    "当班": False,
    "车站范围": [],
    "权限": [],
}


def get_operator(operator_id: str | None) -> dict[str, Any]:
    """按工号解析当前操作人；解析不到时按无任何权限的访客处理。"""
    if operator_id:
        for operator in OPERATORS:
            if operator["id"] == operator_id:
                return operator
    return dict(_ANONYMOUS)


def scope_text(operator: dict[str, Any]) -> str:
    stations = operator.get("车站范围") or []
    if GLOBAL_SCOPE in stations:
        return "全线各站"
    return "、".join(stations) if stations else "（无授权车站）"


def can_reach_station(operator: dict[str, Any], station: str) -> bool:
    stations = operator.get("车站范围") or []
    return GLOBAL_SCOPE in stations or station in stations


def evaluate(
    operator: dict[str, Any],
    action: str,
    entry: dict[str, Any],
) -> tuple[bool, str]:
    """校验操作人能否对指定电源屏执行动作，返回(是否放行, 拦截原因)。

    顺序：动作合法 -> 功能权限 -> 车站归属 -> 当班要求 -> 停用状态。
    """
    label = PERMISSION_LABELS.get(action)
    if label is None:
        return False, f"动作「{action}」不属于信号电源可执行范围"

    if action not in operator.get("权限", []):
        return False, f"无权执行「{action}」：缺少{label}"

    station = str(entry.get("所属车站") or "")
    if not can_reach_station(operator, station):
        return (
            False,
            f"无权操作{station}的电源屏：您的可操作范围为{scope_text(operator)}",
        )

    if action in DUTY_REQUIRED_ACTIONS and not operator.get("当班"):
        return False, f"「{action}」只能由当班人员执行，您当前不在当班时段"

    if entry.get("启用状态") != "启用":
        return False, "该电源屏已停用，不能再执行任何操作"

    return True, ""


def operator_catalog() -> list[dict[str, Any]]:
    """对外的值班名册：附上权限中文名，供前端切换身份与展示。"""
    items: list[dict[str, Any]] = []
    for operator in OPERATORS:
        item = dict(operator)
        item["权限说明"] = [PERMISSION_LABELS.get(p, p) for p in operator["权限"]] or ["仅查看"]
        items.append(item)
    return items
