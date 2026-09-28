"""轨道交通信号检修管理平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.errors import DomainError
from app.routers import ROUTERS
from app.store import store

app = FastAPI(title="轨道交通信号检修管理平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DomainError)
def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """把业务越权/冲突统一翻译成结构化响应，依赖注入阶段抛出的也能正确返回状态码。"""
    detail: dict[str, object] = {"ok": False, "message": exc.message}
    if exc.missing_permission:
        detail["missing_permission"] = exc.missing_permission
    if exc.duplicate:
        detail["duplicate"] = True
    return JSONResponse(status_code=exc.status_code, content={"detail": detail})


for module in ROUTERS:
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。"""
    return store.overview()
