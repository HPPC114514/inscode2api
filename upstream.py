#!/usr/bin/env python3
"""上游 HTTP 客户端（仅标准库 urllib，零第三方依赖）。

- GET  /v1/models：纯 Bearer 即通（已验证），不调用签名器
- POST /v1/chat/completions：发往上游前调用 signer.build_sign_headers
  （见 build_headers 中「签名集成点」）
- 流式：stream=true 时按行读取上游 SSE 响应，逐行 yield 供 server 逐块转发
- 连接/超时/非 2xx 均不抛进程外异常：连接失败抛 UpstreamConnectionError，
  非 2xx 以 (status, body) 返回，由 server 统一映射为 OpenAI 风格错误。
"""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request

import signer

REQUEST_TIMEOUT = 60       # 非流式请求超时（秒）
STREAM_TIMEOUT = 600       # 流式读行超时（秒）

CHAT_PATH = "/api/v1/chat/completions"
MODELS_PATH = "/api/v1/models"


class UpstreamConnectionError(Exception):
    """上游连接层失败（DNS / 连接 / TLS / 超时）。"""


def _status(resp) -> int:
    return getattr(resp, "status", None) or getattr(resp, "code", 0)


def _close(resp) -> None:
    try:
        resp.close()
    except Exception:
        pass


def build_headers(cfg, method: str, path: str, body: bytes | None,
                  require_sign: bool, accept: str) -> dict[str, str]:
    """构造上游请求头。

    === 签名集成点 ===
    POST /v1/chat/completions 且未设 INCODE2API_SKIP_SIGN=1 时
    （require_sign=True 且 cfg.skip_sign=False），会调用
    signer.build_sign_headers(...)，把其返回的所有头部 dict.update 合并进
    本请求，叠加在 Authorization / Content-Type / Accept 之上。

    集成签名只需在 signer.py 里实现 build_sign_headers：
      * 入参已含 api_key / key_id / sign_key_b64 / device_id / method /
        path / body（原始请求体字节）
      * 返回值 dict[str, str] 原样 add_header 到上游请求
      * 签名缺失/错误时上游返回 401 invalid_client_signature，可联调验证

    GET /v1/models（require_sign=False）为纯 Bearer 即通，不调用签名器。
    """
    headers = {
        "Authorization": "Bearer " + cfg.api_key,
        "Content-Type": "application/json",
        "Accept": accept,
        "User-Agent": "inscode2api/0.1",
    }
    if require_sign and not cfg.skip_sign:
        # 签名集成点：真实实现返回后会以 dict.update 合并进 headers
        sig_headers = signer.build_sign_headers(
            api_key=cfg.api_key,
            key_id=cfg.key_id,
            sign_key_b64=cfg.sign_key_b64,
            device_id=cfg.device_id,
            method=method,
            path=path,
            body=body or b"",
        )
        headers.update(sig_headers)
    return headers


def open_request(cfg, method: str, path: str, body: bytes | None, *,
                 require_sign: bool, accept: str, timeout: int):
    """打开上游连接。

    - 2xx 与非 2xx 都返回响应对象（HTTPError 同样有 status/read），
      由调用方读 body 后自行判断；
    - 连接层失败（DNS/TLS/拒绝/超时）抛 UpstreamConnectionError。
    """
    url = cfg.base_url + path
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in build_headers(cfg, method, path, body, require_sign, accept).items():
        req.add_header(k, v)
    try:
        return cfg.opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return e  # 非 2xx：响应对象
    except (urllib.error.URLError, OSError, http.client.HTTPException,
            TimeoutError) as e:
        raise UpstreamConnectionError(f"{method} {path} 连接上游失败: {e!r}") from e


def models_list(cfg, timeout: int = REQUEST_TIMEOUT) -> tuple[int, bytes]:
    """GET /v1/models，返回 (status, body_bytes)。"""
    resp = open_request(cfg, "GET", MODELS_PATH, None,
                        require_sign=False, accept="application/json",
                        timeout=timeout)
    try:
        return _status(resp), resp.read()
    finally:
        _close(resp)


def _line_iter(resp, timeout: int):
    """按行读取上游 SSE 响应（迭代器，逐行 yield 原始字节）。"""
    try:
        while True:
            line = resp.readline()
            if not line:
                break
            yield line
    finally:
        _close(resp)


def chat(cfg, payload: dict, *, stream: bool,
         timeout: int | None = None) -> tuple[int, bytes | None, object | None]:
    """POST /v1/chat/completions。

    返回 (status, body, lines)：
      - 流式且 2xx：body=None，lines=逐行迭代器（每项 bytes，含 data: [DONE]）
      - 其余情况：lines=None，body=完整响应字节（非 2xx 由调用方映射错误）

    签名头由 signer.build_sign_headers 生成（算法已逆向并验证，见 SIGN_ALGO.md）。
    签名错误时上游返回 401 invalid_client_signature，由调用方映射错误。
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    accept = "text/event-stream" if stream else "application/json"
    timeout = timeout or (STREAM_TIMEOUT if stream else REQUEST_TIMEOUT)
    resp = open_request(cfg, "POST", CHAT_PATH, body,
                        require_sign=True, accept=accept, timeout=timeout)
    status = _status(resp)
    if stream and 200 <= status < 300:
        return status, None, _line_iter(resp, timeout)
    try:
        return status, resp.read(), None
    finally:
        _close(resp)
