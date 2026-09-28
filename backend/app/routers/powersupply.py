"""信号电源接口：维护电源屏，覆盖登记波动、切换备用、处理故障、修改配置等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services import powersupply_auth as auth
from app.services.powersupply import service

router = APIRouter(prefix="/api/powersupply", tags=["信号电源"])

LIST_FIELDS = [
    "电源屏编号", "所属车站", "输入电压", "输出电压", "输出电流",
    "模块配置", "切换装置", "电源状态", "启用状态", "经手人",
]
STATUSES = ["供电正常", "电压波动", "模块故障", "备用供电"]


def _current_operator(x_operator_id: str | None) -> dict[str, Any]:
    """从请求头解析当前操作人；缺省时视为无权限访客。"""
    return auth.get_operator(x_operator_id)


@router.get("/operators")
def list_operators() -> dict[str, Any]:
    """返回值班名册（岗位、车站范围、权限、当班状态），供前端选择当前身份。"""
    return {"items": auth.operator_catalog()}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按电源屏编号检索"),
    status: str | None = Query(default=None, description="供电正常、电压波动、模块故障、备用供电"),
    page: int = 1,
    size: int = 20,
    x_operator_id: str | None = Header(default=None),
) -> PageResult[dict]:
    """按电源屏编号与状态过滤信号电源列表；逐行附上当前操作人的动作授权结果。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    operator = _current_operator(x_operator_id)
    items, total = service.list_entries(
        operator=operator, keyword=keyword, status=status, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(x_operator_id: str | None = Header(default=None)) -> dict[str, Any]:
    """导出信号电源清单：返回当前过滤条件下的全量数据（含经手人，与记录详情一致）。"""
    operator = _current_operator(x_operator_id)
    items, total = service.list_entries(operator=operator, page=1, size=10000)
    return {"module": "powersupply", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条电源屏明细（含完整操作台账）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"电源屏 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(
    payload: EntryPayload,
    x_operator_id: str | None = Header(default=None),
) -> ActionResult:
    """登记一条电源屏，缺字段或越权时说明原因而不是静默丢弃。"""
    operator = _current_operator(x_operator_id)
    entry, missing, reason = service.create_entry(payload.values, operator)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if entry is None:
        return ActionResult(ok=False, message=reason)
    return ActionResult(ok=True, message=f"电源屏已登记，经手人：{operator['姓名']}", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    x_operator_id: str | None = Header(default=None),
) -> ActionResult:
    """对单条电源屏执行登记波动、切换备用、处理故障；越权、停用、重复操作都会被拦下。"""
    operator = _current_operator(x_operator_id)
    action = str(payload.values.get("action") or "").strip()
    entry, message, applied = service.run_action(entry_id, action, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry, applied=applied)


@router.post("/{entry_id}/config", response_model=ActionResult)
def update_config(
    entry_id: int,
    payload: EntryPayload,
    x_operator_id: str | None = Header(default=None),
) -> ActionResult:
    """修改输入电压、模块配置；只读账号与越站操作会被拦下并说明缺少的权限。"""
    operator = _current_operator(x_operator_id)
    entry, message = service.update_config(entry_id, payload.values, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
