# LangChain Agent MVP

一个可以直接运行的最小 Agent 服务，包含：

- `uv`
- FastAPI
- LangChain `create_agent`
- vLLM OpenAI-compatible API
- Tavily web search
- Docker sandbox
- SSE streaming
- 基于 LangGraph `InMemorySaver` 的 thread conversation state

## 1. 架构

```text
FastAPI
   |
   v
AgentService
   |
   v
LangChain create_agent
   |---- web_search ------> Tavily
   |---- bash_exec --------> Docker sandbox
   |---- python_exec ------> Docker sandbox
   |---- python_run_script -> Docker sandbox
   |
   +---- InMemorySaver (thread_id)
```

FastAPI 服务本身建议运行在宿主机；Docker 仅用于执行 Agent 生成的 shell/Python 任务。这样 MVP 不需要把 `/var/run/docker.sock` 暴露给 API 容器。

## 2. 环境要求

- Python 3.12+
- uv
- Docker Engine
- 一个支持 OpenAI-compatible Chat Completions + tool calling 的 vLLM 服务
- Tavily API Key

## 3. 安装

```bash
cd langchain-agent-mvp
uv sync
cp .env.example .env
```

填写 `.env` 中的：

```dotenv
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_API_KEY=EMPTY
LLM_MODEL=Qwen/Qwen3-8B
TAVILY_API_KEY=tvly-xxxxxxxx
API_TOKEN=your-secret-token
```

`LLM_MODEL` 必须与 vLLM 实际暴露的 model 名称一致。

`API_TOKEN` 为 `/v1` 端点的 Bearer 鉴权令牌;**留空则鉴权关闭**,服务启动时会打 WARNING 提醒。`/healthz` 始终开放(仅返回模型名,不泄露 LLM base_url)。

## 4. 构建 sandbox 镜像

```bash
docker build -t agent-sandbox:py312 ./sandbox-image
```

测试：

```bash
docker run --rm \
  --network none \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m \
  agent-sandbox:py312 \
  bash -lc 'python -c "print(1 + 2)"'
```

## 5. 启动 vLLM

vLLM 官方提供 OpenAI-compatible `/v1` API；自动 tool calling 需要开启 `--enable-auto-tool-choice` 并指定与模型匹配的 `--tool-call-parser`。

例如 Qwen3-8B，可以从下面开始：

```bash
vllm serve Qwen/Qwen3-8B \
  --host 0.0.0.0 \
  --port 8000 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

如果你使用其它模型，请按照该模型在当前 vLLM 版本中的 tool parser 配置修改最后一行。不要机械地把 `hermes` 用到所有模型。

也可以直接运行官方 vLLM Docker 镜像：

```bash
docker run --rm --runtime nvidia --gpus all \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -p 8000:8000 \
  --ipc=host \
  vllm/vllm-openai:latest \
  Qwen/Qwen3-8B \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

## 6. 启动 Agent API

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8061
```

也可以直接用配置里的 `HOST` / `PORT`：

```bash
uv run python -m app.main
```

健康检查：

```bash
curl http://127.0.0.1:8061/healthz
```

配置了 `API_TOKEN` 后，业务端点需要带 Bearer 头：

```bash
curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H "Authorization: Bearer $API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好"}'
```

## 7. 测试普通对话

```bash
curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好，请简单介绍一下你自己"}'
```

## 8. 测试 Python 执行

```bash
curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message":"用 Python 计算 1 到 10000 的平方和，并告诉我结果"}'
```

## 9. 测试 Bash

```bash
curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message":"在工作区创建 hello.txt，内容写 hello agent，然后读取它"}'
```

## 10. 测试 Web Search

```bash
curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message":"搜索一下 Python 当前最新稳定版本，并给出来源"}'
```

## 11. SSE 事件格式

服务会发送类似：

```text
event: start
data: {"thread_id":"..."}

event: tool_start
data: {"tool":"python_exec","input":{...}}

event: tool_end
data: {"tool":"python_exec","output":"..."}

event: token
data: {"text":"..."}

event: done
data: {"thread_id":"..."}
```

前端可以分别处理：`start`、`tool_start`、`tool_end`、`token`、`error`、`done`。

## 12. 对话记忆

请求带相同 `thread_id` 即可复用该线程的 LangGraph checkpoint：

```bash
curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"thread_id":"demo-001","message":"我喜欢 Python"}'

curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"thread_id":"demo-001","message":"我刚才说我喜欢什么？"}'
```

当前使用 `InMemorySaver`，适合 MVP / 调试。进程重启后数据会丢失；生产环境应换成 PostgreSQL checkpointer。

## 13. Sandbox 安全边界

当前容器默认：

- `--network none`
- `--cap-drop ALL`
- `--security-opt no-new-privileges`
- `--read-only`
- `/tmp` 和 `/run` 使用 tmpfs
- CPU / 内存 / PID 数限制
- 非 root 用户 `1000:1000`
- 只有当前 thread 的 `/workspace` 目录以 RW 挂载
- 不挂载 Docker socket
- 不暴露宿主机文件系统

这只是 MVP 的隔离层，不等同于经过安全审计的生产级不可信代码执行平台。

workspace 磁盘增长由后台清理任务兜底：每小时扫描一次，删除超过
`SANDBOX_WORKSPACE_TTL_DAYS` 天无任何文件活动的 thread workspace（设 0 关闭）。

## 14. 测试

```bash
uv run pytest -q      # 单元 / API 测试，不需要 Docker 与外部 LLM
uv run ruff check .
```

测试覆盖：SSE 端点事件框架与鉴权（401/200）、事件映射、执行工具的 JSON 契约与
路径安全、workspace TTL 清理、退出码信号语义。测试不触碰真实 Docker 与 LLM。

## 15. 生产化时优先改造

1. `InMemorySaver` -> PostgreSQL `AsyncPostgresSaver`
2. 为工具增加权限策略和 Human-in-the-loop（web_search 注入指令 -> 沙箱执行是最高危路径）
3. sandbox 改成独立 worker / microVM / 专用执行服务
4. 增加执行配额、并发限制与限流（Bearer 鉴权与 workspace TTL 清理已内置）
5. 接入 LangSmith tracing / evaluation
6. SSE 增加 request_id、tool_call_id、usage、重试和取消机制
7. 对 `web_search` 增加 `open_url` / extract，形成搜索 -> 阅读网页流程
