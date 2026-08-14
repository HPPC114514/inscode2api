#!/usr/bin/env python3
"""OpenAI 兼容格式转换。

- taotoken_models_to_openai：上游 GET /v1/models 自定义格式 → OpenAI 格式
- error_payload / upstream_error_payload：任意上游状态/正文 → {"error": {...}}
- normalize_chat_request：OpenAI 兼容请求体最小校验/规范化（基本透传，
  保留 reasoning_effort / thinking 等 taotoken 扩展参数）
"""
from __future__ import annotations

import json
from typing import Any

# 上游 HTTP 状态码 → OpenAI 错误类型
_STATUS_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    402: "insufficient_quota",
    403: "permission_error",
    404: "not_found_error",
    405: "method_not_allowed",
    408: "request_timeout",
    409: "conflict_error",
    422: "invalid_request_error",
    429: "rate_limit_error",
    500: "server_error",
    502: "bad_gateway",
    503: "service_unavailable",
    504: "gateway_timeout",
}


def _status_type(status: int) -> str:
    return _STATUS_TYPES.get(status, "api_error")


def taotoken_models_to_openai(payload: dict) -> dict:
    """taotoken GET /v1/models 响应 → OpenAI /v1/models 响应。

    上游结构：{"object":"list","data":[{"id":...,"model":...,"type":"chat",...}]}
    OpenAI 结构：{"object":"list","data":[{"id":...,"object":"model",
                  "created":...,"owned_by":...}]}
    """
    data = []
    for m in payload.get("data") or []:
        mid = m.get("id") or m.get("model")
        if not mid:
            continue
        data.append({
            "id": mid,
            "object": "model",
            "created": 0,  # 上游未提供创建时间戳，固定用 0
            "owned_by": "taotoken",
        })
    return {"object": "list", "data": data}


def error_payload(status: int, message: str, code: str | None = None,
                  param: Any = None) -> dict:
    """构造 OpenAI 风格错误对象 {"error": {...}}。"""
    return {
        "error": {
            "message": message,
            "type": _status_type(status),
            "param": param,
            "code": code,
        }
    }


def upstream_error_payload(status: int, body: bytes) -> tuple[int, dict]:
    """把上游非 2xx 响应映射成 (HTTP状态, OpenAI错误JSON)。

    上游若已返回 {"error": {...}} 或 {"message": ..., "code": ...}，
    尽量透传其中的 message/code；否则用兜底文案。
    """
    data: dict = {}
    if body:
        try:
            parsed = json.loads(body.decode("utf-8", "replace"))
            if isinstance(parsed, dict):
                data = parsed
        except (ValueError, TypeError):
            data = {}

    err = data.get("error") if isinstance(data.get("error"), dict) else None
    if err:
        message = err.get("message") or data.get("message") or "upstream error"
        code = err.get("code") or err.get("type") or None
    else:
        message = data.get("message") or f"upstream error (HTTP {status})"
        code = data.get("code") or None
        if isinstance(code, int):
            code = str(code)

    if not isinstance(message, str) or not message:
        snippet = body[:200].decode("utf-8", "replace")
        message = f"upstream error (HTTP {status}): {snippet}"

    if not isinstance(code, str):
        code = None
    return status, error_payload(status, message, code=code)


def normalize_chat_request(payload: dict) -> dict:
    """OpenAI 兼容请求体 → 上游请求体（最小映射/校验）。

    上游请求体基本就是 OpenAI 格式，这里仅做最小校验与规范化：
    - 必须包含 model 与非空 messages
    - stream 字段规范为 bool
    其余字段（max_tokens、temperature、reasoning_effort、thinking 等）
    一律透传，不做删改。
    """
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    model = payload.get("model")
    messages = payload.get("messages")
    if not model:
        raise ValueError("missing required field: model")
    if not isinstance(messages, list) or not messages:
        raise ValueError("missing required field: messages")
    payload = dict(payload)
    if "stream" in payload:
        payload["stream"] = bool(payload["stream"])
    return payload
