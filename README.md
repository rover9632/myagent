# LangChain Agent MVP

一个可以直接运行的最小 Agent 服务，包含：

- `uv`
- FastAPI
- PostgreSQL 用户体系（注册/登录/会话令牌）
- LangChain `create_agent`
- vLLM OpenAI-compatible API
- Tavily web search
- Docker sandbox（工作区按用户划分）
- 附件上传（落入线程沙箱工作区）
- SSE streaming
- 基于 LangGraph `AsyncPostgresSaver` 的持久化对话记忆（重启不丢）

## 1. 架构

```text
FastAPI
   |---- /v1/auth/* (注册/登录/登出/me) ---> PostgreSQL (users, sessions)
   |
   v
AgentService（所有 /v1/agent/* 需登录会话 Bearer）
   |
   v
LangChain create_agent
   |---- web_search ------> Tavily
   |---- bash_exec --------> Docker sandbox (<user>/<thread> 工作区)
   |---- python_exec ------> Docker sandbox
   |---- python_run_script -> Docker sandbox
   |
   +---- AsyncPostgresSaver (checkpoint 键: <username>:<thread_id>)
```

FastAPI 服务本身建议运行在宿主机；Docker 仅用于执行 Agent 生成的 shell/Python 任务。这样 MVP 不需要把 `/var/run/docker.sock` 暴露给 API 容器。用户/会话与 LangGraph checkpoint 共享同一个 PostgreSQL 连接池（psycopg3）。

## 2. 环境要求

- Python 3.12+
- uv
- Docker Engine
- PostgreSQL 17+（用户、会话与对话记忆；启动时自动建表）
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
PG_URI=postgresql://postgres:your-password@127.0.0.1:5432/myagent
PG_POOL_MIN_SIZE=2
PG_POOL_MAX_SIZE=10
SESSION_TTL_DAYS=30
```

`LLM_MODEL` 必须与 vLLM 实际暴露的 model 名称一致。

`PG_URI` 使用标准 libpq URI 写法（`postgresql://user:password@host:port/dbname`），不接受 SQLAlchemy 方言（如 `postgresql+asyncpg://`）。

鉴权模型：所有 `/v1/agent/*` 端点要求**用户会话 Bearer 令牌**（先经 `/v1/auth/register` 或 `/v1/auth/login` 获取）。`/healthz` 与 `/v1/auth/register`、`/v1/auth/login` 开放；`/healthz` 仅返回模型名，不泄露 LLM base_url。会话默认 30 天过期（`SESSION_TTL_DAYS`），数据库中只保存令牌的 sha256 哈希。

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

启动时需要能连上 PostgreSQL（连不上会立即报错退出，不会静默降级）；首次启动自动建表（users/sessions + LangGraph checkpoint 表，全部幂等）。

健康检查：

```bash
curl http://127.0.0.1:8061/healthz
```

注册一个用户并提取会话令牌，之后业务端点都带这个 Bearer 头：

```bash
TOKEN=$(curl -s http://127.0.0.1:8061/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"your-password"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好"}'
```

已注册过的用户改用 `/v1/auth/login`（每次登录都会签发新令牌）；`/v1/auth/me` 查看当前身份，`/v1/auth/logout` 服务端吊销令牌。

## 7. Web 前端（`web/`）

ChatGPT 风格的 Next.js 对话页，带登录/注册门禁。浏览器只访问同源代理路由（后端未开 CORS）；
代理**原样转发浏览器的 `Authorization` 头**（用户登录会话），Next.js 服务端不再持有任何后端密钥。

```bash
cd web
cp .env.example .env.local   # 只需 BACKEND_URL
npm install
npm run dev                  # 访问 http://localhost:3000
```

`.env.local` 可配置项：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BACKEND_URL` | `http://127.0.0.1:8061` | Agent API 地址 |

特性与约定：

- 未登录显示登录/注册页；会话令牌与用户名存 localStorage（`myagent.auth.v1`），登出时服务端吊销
- 会话列表/界面历史按用户命名空间存浏览器 localStorage（`myagent.threads.<username>.v1`），清缓存即丢；模型记忆在服务端数据库，重启不丢
- 后端暂时不可达不会踢出登录（仅 401 才清除本地会话）；流式请求收到 401 时回落到登录门禁
- 「+」附件上传落入该线程的沙箱工作区 `uploads/`，消息中以芯片展示，模型可按需读取
- AI 回复除最后正式回答外均折叠为「深度思考」，工具调用可展开看 stdout/stderr/exit code
- 回答支持 LaTeX：`$...$` 行内、`$$...$$` 块级（KaTeX 渲染；注意 `$` 货币符号可能被误配对）
- 生产构建：`npm run build && npm start`

以下 `$TOKEN` 均指 §6 中注册/登录得到的会话令牌。

## 8. 测试普通对话

```bash
curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好，请简单介绍一下你自己"}'
```

## 9. 测试 Python 执行

```bash
curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"用 Python 计算 1 到 10000 的平方和，并告诉我结果"}'
```

## 10. 测试 Bash

```bash
curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"在工作区创建 hello.txt，内容写 hello agent，然后读取它"}'
```

## 11. 测试 Web Search

```bash
curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"搜索一下 Python 当前最新稳定版本，并给出来源"}'
```

## 12. SSE 事件格式

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

## 13. 对话记忆

对话记忆由 `AsyncPostgresSaver` 持久化到 PostgreSQL，**进程重启不丢失**。请求带相同 `thread_id` 即可复用该线程的 checkpoint：

```bash
curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"thread_id":"demo-001","message":"我喜欢 Python"}'

curl -N http://127.0.0.1:8061/v1/agent/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"thread_id":"demo-001","message":"我刚才说我喜欢什么？"}'
```

checkpoint 实际按键 `<username>:<thread_id>` 存储（用户名规则天然不含 `:`）：`thread_id` 由客户端自报、存储又是共享的，加用户命名空间后**两个用户使用相同 `thread_id` 也绝不会串到彼此的记忆**。SSE `start`/`done` 事件回显的仍是客户端视角的 `thread_id`。

## 14. Sandbox 安全边界

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

宿主机工作区按用户两级划分：`data/workspaces/<user>/<thread>/`（两级目录名都经过消毒 + sha256 短哈希后缀，防碰撞防穿越）。容器内挂载点不变，仍只见单个 thread 目录映射为 `/workspace`，因此不同用户、不同线程互相不可见。

workspace 磁盘增长由后台清理任务兜底：每小时两级扫描一次，先删除超过 `SANDBOX_WORKSPACE_TTL_DAYS` 天无任何文件活动的 thread 目录，再顺手 `rmdir` 清空掉的用户目录（设 0 关闭清理）。

## 15. 测试

```bash
uv run pytest -q      # 单元 / API 测试，不需要 PostgreSQL、Docker 与外部 LLM
uv run ruff check .
```

测试覆盖：注册/登录/登出/me 全流程（409/401/422/过期会话/登出吊销）、密码哈希与
72 字节边界、SSE 端点事件框架与会话鉴权（401/200）、checkpoint 按用户
命名空间、事件映射、执行工具的 JSON 契约与路径安全、两级 workspace 及其 TTL 清理、
跨用户文件隔离、退出码信号语义。数据库层用内存 `FakeUserStore` + FastAPI dependency
override 替身，**不连真实 PostgreSQL**；真实 SQL 与 bcrypt 由启动自检和冒烟脚本覆盖。
真 Docker 集成测试存在但会在缺少 docker/镜像时自动跳过。

## 16. 生产化时优先改造

1. 登录/注册接口增加限流与验证码（当前仅靠 bcrypt 成本与统一错误信息减缓爆破/枚举）
2. 会话令牌改用 httpOnly cookie 方案替代 localStorage（消除 XSS 窃取面；当前 Bearer 头天然免疫 CSRF）
3. 会话刷新（refresh token）、单用户并发会话上限与「登出所有设备」
4. 用户注销与数据清理（级联删除 sessions/checkpoints/workspaces）
5. 用 alembic 管理 schema 迁移（当前为启动时 `CREATE TABLE IF NOT EXISTS`，只增不改）
6. 为工具增加权限策略和 Human-in-the-loop（web_search 注入指令 -> 沙箱执行是最高危路径）
7. sandbox 改成独立 worker / microVM / 专用执行服务
8. 增加执行配额、并发限制与限流（会话鉴权与 workspace TTL 清理已内置）
9. 接入 LangSmith tracing / evaluation
10. SSE 增加 request_id、tool_call_id、usage、重试和取消机制
11. 对 `web_search` 增加 `open_url` / extract，形成搜索 -> 阅读网页流程
