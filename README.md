# inscode2api

把 CSDN **InsCode** 账号能力封装成 **OpenAI 兼容 API** 的本地代理服务。

- 纯 Python 标准库（`http.server` + `urllib`），**零第三方依赖**（无需 `requests`）。
- 上游为 InsCode 背后的 AI 网关 `https://taotoken.net`。
- 完整实现 InsCode 客户端的 **X-Tt 签名**，可正常调用 `/v1/chat/completions`（流式 / 非流式）。
- 凭据只在本机使用、绝不外发；API key / 签名密钥 / JWT 一律不打印明文。

---

## 目录

- [特性](#特性)
- [前置条件](#前置条件)
- [快速开始](#快速开始)
- [使用教程](#使用教程)
  - [1. curl 直接调用](#1-curl-直接调用)
  - [2. 接入 OpenAI SDK](#2-接入-openai-sdk)
  - [3. 接入第三方客户端](#3-接入第三方客户端)
- [端点](#端点)
- [配置](#配置)
- [签名说明](#签名说明)
- [安全说明](#安全说明)
- [常见问题 FAQ](#常见问题-faq)

---

## 特性

- ✅ 把 InsCode 免费额度（`deepseek-v4-flash` 等）变成标准 OpenAI 接口
- ✅ 支持**非流式**（一次性 JSON）与**流式**（SSE，`data: [DONE]` 透传）
- ✅ `/v1/models` 返回 OpenAI 格式模型列表
- ✅ 自动加载本机 InsCode 凭据，无需手动填密钥
- ✅ 零依赖，复制即用

## 前置条件

1. **已在本机安装并登录过 InsCode 客户端**（产生 `~/.config/inscode/` 下的凭据文件）。
   - Windows 路径：`C:\Users\<你的用户名>\.config\inscode\`
   - macOS / Linux 路径：`~/.config/inscode/`
2. **Python 3.10+**（本项目在 3.14 验证通过）。

## 快速开始

```bash
# 1. 进入项目目录
cd inscode2api

# 2. 启动服务（默认监听 http://127.0.0.1:8000）
python server.py
```

看到以下输出即启动成功：

```
[inscode2api] listening on http://127.0.0.1:8000
[inscode2api] upstream: https://taotoken.net  skip_sign=False
```

验证一下：

```bash
curl http://127.0.0.1:8000/healthz
# {"status": "ok", "service": "inscode2api"}
```

---

## 使用教程

### 1. curl 直接调用

**模型列表：**

```bash
curl http://127.0.0.1:8000/v1/models
```

返回示例：

```json
{
  "object": "list",
  "data": [
    {"id": "deepseek-v4-flash", "object": "model", "created": 0, "owned_by": "taotoken"},
    {"id": "qwen3-vl-8b-instruct", "object": "model", "created": 0, "owned_by": "taotoken"}
  ]
}
```

**非流式聊天：**

```bash
curl -s -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "你好，用一句话介绍你自己"}],
    "max_tokens": 200
  }'
```

**流式聊天（SSE）：**

```bash
curl -sN -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "写一首关于秋天的诗"}],
    "stream": true
  }'
```

> `deepseek-v4-flash` 是推理模型，回复里会带 `reasoning_content`（思考过程）字段；最终答案在 `content` 字段。可额外传 `reasoning_effort`（如 `high` / `max`）控制推理强度。

### 2. 接入 OpenAI SDK

任何 OpenAI 兼容的 SDK，只需把 `base_url` 指向本服务即可。

**Python（openai 库）：**

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="sk-any-value",   # 本服务不校验调用方 key，可填任意非空值
)

resp = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "你好"}],
    stream=True,
)

for chunk in resp:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

**Node.js（openai 库）：**

```js
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://127.0.0.1:8000/v1",
  apiKey: "sk-any-value",
});

const stream = await client.chat.completions.create({
  model: "deepseek-v4-flash",
  messages: [{ role: "user", content: "你好" }],
  stream: true,
});

for await (const chunk of stream) {
  const c = chunk.choices[0]?.delta?.content;
  if (c) process.stdout.write(c);
}
```

### 3. 接入第三方客户端

在支持自定义 OpenAI 兼容 provider 的工具里，填：

- **Base URL / API Endpoint**：`http://127.0.0.1:8000/v1`
- **API Key**：任意非空值（如 `sk-local`）
- **模型**：`deepseek-v4-flash`（或 `/v1/models` 列出的其它模型）

适用的工具（不限于）：

| 工具 | 配置位置 |
|---|---|
| **Cline**（VSCode） | Provider 选 `OpenAI Compatible` → 填 Base URL + API Key + Model |
| **Continue**（VSCode/JetBrains） | `config.json` 里加 OpenAI 兼容 provider |
| **LobeChat** | 服务商选「OpenAI」→ 接口地址填本服务 |
| **ChatBox / Cherry Studio** | 添加自定义 provider |
| **Dify / FastGPT** | 模型供应商选 OpenAI-API-compatible |

> 本服务默认只监听 `127.0.0.1`，只供本机使用。若需局域网内其它机器访问，见[安全说明](#安全说明)。

---

## 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 健康检查 |
| GET | `/v1/models` | OpenAI 格式模型列表（转发 taotoken，纯 Bearer 即通） |
| POST | `/v1/chat/completions` | 聊天补全（自动签名）。`stream:true` 时 SSE 逐块转发 |

请求/响应均为 OpenAI 兼容格式，额外 taotoken 参数（`reasoning_effort`、`thinking` 等）原样透传。

错误统一返回 OpenAI 风格：

```json
{"error": {"message": "...", "type": "authentication_error", "param": null, "code": "..."}}
```

---

## 配置

全部通过环境变量覆盖，无需改代码：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `INCODE2API_CONFIG_DIR` | `~/.config/inscode` | InsCode 凭据目录 |
| `INCODE2API_API_KEY` | 读 taotoken.json | 覆盖 api_key |
| `INCODE2API_BASE_URL` | `https://taotoken.net` | 上游 base url |
| `INCODE2API_HOST` | `127.0.0.1` | 本服务监听地址 |
| `INCODE2API_PORT` | `8000` | 本服务监听端口 |
| `INCODE2API_SKIP_SIGN` | 空 | `=1` 跳过签名直发（联调用） |
| `INCODE2API_PROXY` | 空（禁用系统代理） | 指定 http(s) 代理，如 `http://127.0.0.1:7890` |

凭据来源（`~/.config/inscode/` 下）：
- `taotoken.json` —— `free.api_key`、`free.sign_key.key_id`、`free.sign_key.sign_key`、`free.enabled_models`
- `device.json` —— `device_id`
- `auth.json` —— 登录态 JWT（本项目当前主要用 api_key + sign_key）

查看脱敏后的配置：

```bash
python config.py
```

> 本机存在系统代理时，urllib 默认会走它。本项目**默认显式禁用系统代理**，避免上游连接被劫持；确需代理时用 `INCODE2API_PROXY` 指定。

---

## 签名说明

`POST /v1/chat/completions` 需要携带 InsCode 客户端的 X-Tt 签名，否则上游返回 `401 invalid_client_signature`。

本项目已在 `signer.py` 中完整实现该签名（逆向自 InsCode 客户端），核心算法：

```python
key   = base64.b64decode(sign_key_b64)          # 32 字节原始密钥
canon = f"POST\n{path}\n{ts_ms}\n{nonce_b64}\n{key_id}\n{sha256(body)}"
sign  = HMAC-SHA256(key, canon).hexdigest()
```

生成的头：

- `X-Tt-Keyid`
- `X-Tt-Ts`（毫秒时间戳）
- `X-Tt-Nonce`（base64(16 字节随机)）
- `X-Tt-Sign`（HMAC hex）
- `X-Tt-Sign-Version: v1`
- `X-Tt-Device-Id`

---

## 安全说明

- 本服务**默认只监听 `127.0.0.1`**，不暴露到局域网/公网。
- api_key / sign_key / JWT 只在本机构造上游请求时使用，任何日志、README、错误响应都不含明文。
- **本代理不校验调用方身份**：`/v1/chat/completions` 的 `Authorization` 会被忽略并替换为你自己的 InsCode 凭据。因此：
  - 若你监听 `0.0.0.0` 或暴露到公网，任何人可借你的 InsCode 额度发起请求 —— **务必只在可信网络里这样用，或自行加一层鉴权**。
- 建议仅在本机使用。

---

## 常见问题 FAQ

**Q：启动报「需要签名但 taotoken.json 缺少 free.sign_key」？**
A：说明你没登录过 InsCode 或凭据文件不完整。先在 InsCode 客户端登录一次，让它生成 `taotoken.json`；或设 `INCODE2API_SKIP_SIGN=1` 只跑不需要签名的端点（`/v1/models`）。

**Q：请求返回 `401 invalid_client_signature`？**
A：签名密钥（`sign_key`）可能已过期（`taotoken.json` 里有 `expire_at`）。重新启动 InsCode 客户端刷新凭据，再重启本服务即可。

**Q：`/v1/chat/completions` 返回 404（openresty 页面）？**
A：上游路径必须是 `/api/v1/chat/completions`（带 `/api/v1`），且 host 是 `taotoken.net`。本项目的 `INCODE2API_BASE_URL` 默认已正确，别改成 `api.taotoken.net` + 错误路径组合。

---

## 免责声明

本项目仅供个人学习与技术研究，用于**你自己账号**的本地 API 封装。请遵守 InsCode / CSDN 的服务条款，勿用于违规用途，勿将账号凭据或本服务暴露给他人。

## 许可

[Mozilla Public License 2.0](./LICENSE)


*Co-Authored-By Kimi-k3 GLM-5.2 Deepseek-v4-pro-0813 Deepseek-v4-flash-0731 On ZCode*
