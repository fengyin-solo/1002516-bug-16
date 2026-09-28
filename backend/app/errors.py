"""统一的业务异常：服务层抛出，路由层翻译成对应的 HTTP 状态码与可读说明。"""
from __future__ import annotations


class DomainError(Exception):
    """业务规则被违反时抛出。

    status_code：建议的 HTTP 状态（401 未登录 / 403 越权 / 404 不存在 / 409 冲突）。
    missing_permission：越权时缺失的具体权限，方便前端直接提示给值班人员。
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        missing_permission: str | None = None,
        duplicate: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.missing_permission = missing_permission
        self.duplicate = duplicate
