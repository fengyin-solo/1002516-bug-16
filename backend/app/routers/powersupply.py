"""信号电源接口：电源屏维护、动作执行、模块配置、操作记录查询。

写操作通过 X-Operator-Id 请求头携带当前操作人工号，服务端据此核对
车站归属、角色权限与当班状态；越权返回 403 并说明缺失的权限。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.identity import (
    Operator,
    list_operators,
    require_operator,
)
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.powersupply import PowersupplyService

router = APIRouter(prefix="/api/powersupply", tags=["信号电源"])

service = PowersupplyService()

STATUSES = ["供电正常", "电压波动", "模块故障", "备用供电"]


def _panel_view(entry: dict[str, Any]) -> dict[str, Any]:
    """列表/台账口径：投运状态与最近操作人都来自电源屏上同步好的字段。"""
    view = dict(entry)
    view["状态"] = entry.get("电源状态") or entry.get("status")
    view["投运状态"] = "在用" if entry.get("enabled", True) else "已停用"
    return view


# ---------------- 身份目录 ----------------
@router.get("/operators")
def get_operators() -> dict[str, Any]:
    """当前可切换的操作人名单：含所属车站、角色与当班状态。"""
    return {"items": list_operators()}


# ---------------- 操作记录 ----------------
@router.get("/records", response_model=PageResult[dict])
def list_records(
    entry_id: int | None = Query(default=None, description="按电源屏 id 过滤台账"),
    station: str | None = Query(default=None, description="按所属车站过滤台账"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """电源屏操作记录台账；可按单屏或车站过滤。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_records(entry_id=entry_id, station=station, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/records/{record_id}", response_model=dict)
def get_record(record_id: int) -> dict[str, Any]:
    """操作记录详情：经手人与台账列表来自同一条记录。"""
    record = service.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"操作记录 {record_id} 不存在")
    return record


# ---------------- 导出（静态路径必须放在 /{entry_id} 之前） ----------------
@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出信号电源清单：返回全量数据，含最近操作人，便于与台账核对。"""
    items, total = service.list_entries(page=1, size=10000)
    return {
        "module": "powersupply",
        "total": total,
        "items": [_panel_view(item) for item in items],
    }


# ---------------- 电源屏列表 / 明细 ----------------
@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按电源屏编号检索"),
    station: str | None = Query(default=None, description="按所属车站过滤"),
    status: str | None = Query(default=None, description="供电正常、电压波动、模块故障、备用供电"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按电源屏编号、所属车站与状态过滤列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, station=station, status=status, page=page, size=size)
    return PageResult(items=[_panel_view(item) for item in items], total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict[str, Any]:
    """读取单条电源屏明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"电源屏 {entry_id} 不存在或已归档")
    return _panel_view(entry)


# ---------------- 动作 / 配置 ----------------
@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    operator: Operator = Depends(require_operator),
) -> ActionResult:
    """登记波动 / 切换备用 / 处理故障。

    权限不足、越站、非当班、停用屏、重复操作都会被拦下并说明原因。
    """
    action = str(payload.values.get("action") or "").strip()
    request_id = str(payload.values.get("request_id") or "").strip() or None
    entry, record = service.run_action(
        entry_id, action, operator, request_id=request_id, remark=payload.remark
    )
    return ActionResult(
        ok=True,
        message=f"电源屏已{action}（经手人：{record['经手人']}，记录号：{record['记录号']}）",
        entry=_panel_view(entry),
    )


@router.put("/{entry_id}/config", response_model=ActionResult)
def update_config(
    entry_id: int,
    payload: EntryPayload,
    operator: Operator = Depends(require_operator),
) -> ActionResult:
    """修改输入电压 / 模块配置：仅持有「模块配置修改」权限的本车站人员可操作。"""
    request_id = str(payload.values.pop("request_id", "") or "").strip() or None
    entry, record = service.update_config(
        entry_id, payload.values, operator, request_id=request_id
    )
    return ActionResult(
        ok=True,
        message=f"模块配置已更新（经手人：{record['经手人']}，记录号：{record['记录号']}）",
        entry=_panel_view(entry),
    )
