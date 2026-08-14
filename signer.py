#!/usr/bin/env python3
"""Taotoken X-Tt 签名模块（已验证）。

算法来源：InsCode.exe 静态逆向（`src/kernel_host/signer.rs`）+ 二进制补丁明文抓包
真实样本反推，详见 `../inscode2api-probe/SIGN_ALGO.md`。

已用本机凭据对真实上游 `taotoken.net` 验证：HTTP 200 + deepseek-v4-flash 正常回复。

算法
----
- 密钥：`base64.b64decode(free.sign_key.sign_key)`（32 字节原始密钥）
- 摘要：标准 HMAC-SHA256，hex 输出（64 位字符）
- 时间戳：epoch 毫秒（13 位）
- nonce：16 字节随机数，base64 编码（24 位字符），同时出现在头与 canonical
- canonical：
      POST\n/api/v1/chat/completions\n{ts}\n{nonce_b64}\n{key_id}\n{body_sha256}
  其中 body_sha256 = sha256(请求体原始字节) 的 hex 输出
- 签名 = HMAC-SHA256(key=sign_key, msg=canonical).hexdigest()

请求头
------
- Authorization: Bearer <api_key>               （OpenAI 风格）
- Content-Type: application/json
- X-Tt-Keyid: <key_id>                          （注意：是 Keyid 不是 Key-Id）
- X-Tt-Ts: <epoch 毫秒>
- X-Tt-Nonce: <base64(16 字节随机)>
- X-Tt-Sign: <HMAC hex>
- X-Tt-Sign-Version: v1                          （注意：值是 'v1' 不是 '1'）
- X-Tt-Device-Id: <device_id>

上游端点
--------
- chat: `https://taotoken.net/api/v1/chat/completions`（host 是 taotoken.net，路径含 /api/v1）
- models: `https://taotoken.net/api/v1/models`（纯 Bearer，路径含 /api/v1）
  > 注意：models 也可用 `https://api.taotoken.net/v1/models`（两个 host 都能 200），
  > 但本 proxy 统一走 `https://taotoken.net`，避免混用 host 导致签名/路径不一致。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

# 已验证的上游端点（与 InsCode 客户端一致）
CHAT_PATH = "/api/v1/chat/completions"
DEFAULT_SIGN_VERSION = "v1"


def _hmac_hex(key: bytes, msg: bytes) -> str:
    """HMAC-SHA256(key, msg) → hex 小写。"""
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def build_sign_headers(api_key: str, key_id: str, sign_key_b64: str,
                       device_id: str, method: str, path: str,
                       body: bytes) -> dict[str, str]:
    """生成发往 taotoken 上游聊天端点的 X-Tt-* 签名头。

    参数：
        api_key       用户 api_key（Bearer 前缀之外的部分）。本签名不直接使用，
                      但用作 Authorization 头（由调用方加，本函数不返回该头）。
        key_id        free.sign_key.key_id（32 位 hex）
        sign_key_b64  free.sign_key.sign_key（base64 字符串，b64decode 后是 32 字节 HMAC 密钥）
        device_id     device.json 的 device_id
        method        HTTP 方法（仅 "POST" 需要签名）
        path          上游路径。canonical 中固定为 `/api/v1/chat/completions`。
                      若传入别的路径，会按传入值构建 canonical（一般不要这么做）。
        body          请求体原始字节，用于 sha256

    返回：
        dict[str, str]：X-Tt-* 头。调用方以 `headers.update(...)` 合并进上游请求。
        Authorization / Content-Type / Accept 等公共头由调用方加，本函数不包含。

    验证：
        2026-08-14，真实凭据对该算法在 taotoken.net 上验证：HTTP 200 + 正常回复。
    """
    if method != "POST":
        # 非 POST（如 GET /v1/models）为纯 Bearer，不需要签名
        return {}

    # 解析 32 字节原始 HMAC 密钥
    key = base64.b64decode(sign_key_b64)

    # 时间戳与 nonce（每次请求新生成；nonce 在头与 canonical 中一致）
    ts_ms = str(int(time.time() * 1000))
    nonce_b64 = base64.b64encode(os.urandom(16)).decode("ascii")

    # body sha256 hex
    body_sha = hashlib.sha256(body).hexdigest()

    # canonical（已与真实抓包样本逐一比对：HMAC 计算值 == X-Tt-Sign）
    canon = f"POST\n{path}\n{ts_ms}\n{nonce_b64}\n{key_id}\n{body_sha}"
    sign = _hmac_hex(key, canon.encode("utf-8"))

    return {
        "X-Tt-Keyid":        key_id,
        "X-Tt-Ts":           ts_ms,
        "X-Tt-Nonce":        nonce_b64,
        "X-Tt-Sign":         sign,
        "X-Tt-Sign-Version": DEFAULT_SIGN_VERSION,
        "X-Tt-Device-Id":    device_id,
    }