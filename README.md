# NAT WebUI 项目说明 / 接手文档

轻量 NAT / 家宽 / 代理节点管理面板。目标是把用户常用的 NAT 小鸡、家宽落地机、前置中转机统一记录、部署、订阅分发，并支持“前置入口 -> 后端落地”的链式节点。

当前实际运行目录：按部署环境决定；生产环境建议使用 `/opt/natxyz` 或独立工作目录。

GitHub 仓库：`yun8811/natwebui`

运行端口：`8788`（可通过 `NAT_WEBUI_PORT` 环境变量自定义）

生产启动脚本：`scripts/run-prod.sh`（foreground/systemd）、`scripts/start.sh`（nohup 后台）

重要原则：改功能时先确认实际运行目录，在干净工作区验证并完成脱敏扫描后再提交 push 到 GitHub。

## 当前核心能力

- 管理员登录
- 节点新增 / 编辑 / 删除 / 详情页
- 节点标签管理
- 节点名内联编辑
- 节点表格前端排序
- 地区代码 / 国旗 / 订阅备注生成
- 直连 VLESS Reality 部署 / 重装，支持同一 VPS 多直连节点合并为多个 inbound
- Alpine / Debian 基础依赖补装
- DDNS / 域名型 NAT 节点部署
- Agent 上报与在线状态回填
- v2rayN 订阅
- Clash 订阅
- 订阅 token 轮换
- 节点类型页签：`直连` / `链式` / `仅导入`
- 链式节点：前置 sing-box Reality inbound -> 后端 VLESS Reality outbound
- 仅导入节点：直接粘贴已有 VLESS 链接，可进入独立订阅，也可作为链式后端/落地

## 运行方式

本机生产运行应使用 `scripts/start.sh`（nohup 后台模式）或 `scripts/run-prod.sh`（foreground/systemd 模式）：

**start.sh（推荐，后台运行）：**

```bash
cd /opt/natxyz
bash scripts/start.sh
```

**run-prod.sh（前台/写入 systemd unit）：**

```bash
cd /opt/natxyz
nohup bash scripts/run-prod.sh > logs/uvicorn.out 2> logs/uvicorn.err & echo $! > data/uvicorn.pid
```

停止 / 重启：

```bash
cd /opt/natxyz
kill -TERM $(cat data/uvicorn.pid) 2>/dev/null || true
sleep 1
bash scripts/start.sh
```

不要直接手动跑 `uvicorn app.main:app ...`，否则可能不会加载 `.env.runtime`，登录密码会退回开发默认值。

检查进程是否加载生产环境变量：

```bash
tr '\0' '\n' < /proc/$(cat data/uvicorn.pid)/environ | grep '^NAT_WEBUI_' | sed -E 's/(NAT_WEBUI_ADMIN_PASSWORD=).*/\1[hidden]/; s/(NAT_WEBUI_SESSION_SECRET=).*/\1[hidden]/'
```


## GitHub 上传脱敏清单

本仓库已按开源上传要求移除运行数据和真实节点信息。后续提交前也应按本清单复查。

### 未上传的运行数据

以下内容只允许存在于服务器本地，不进入 GitHub：

- `data/*.db`：SQLite 数据库，包含节点、订阅 token、部署记录、标签、在线状态等运行数据。
- `data/geo_cache.json`：IP/地区缓存，可能包含真实节点 IP。
- `logs/*.log`：运行日志，可能包含请求、部署错误、节点地址或敏感上下文。
- `.env`、`.env.*`、`.env.runtime`：生产环境变量，包含管理员密码、session secret、数据库路径等。
- `.venv/`、`.test-venv*/`：本地/测试虚拟环境，不属于源码。

仓库中仅保留 `data/.gitkeep` 和 `logs/.gitkeep` 作为空目录占位。

### 已替换的真实信息

- 真实服务器 IP / 节点 IP：替换为文档保留地址，例如 `198.51.100.x`、`203.0.113.x`。
- 真实域名 / DDNS / 业务域名：替换为 `example.com`、`node.example.com`、`backend.example.com`、`www.example.com` 等示例域名。
- 真实 root 密码 / SSH 密码：不写入源码；测试里只使用 `test-pass`、`new-pass`、`dup-pass`、`custom-pass` 等无效占位值。
- 真实 root 登录命令：文档或提示中使用 `<user>`、占位地址或泛化说明，避免保留真实 `root@真实IP`。
- 真实 VLESS / VMess / Trojan / SS 节点链接：不提交；测试中仅保留无效 UUID、保留地址、`example.com` 组成的假链接。
- 真实 API Key / Token / 私钥 / Session Secret：不提交；数据库展示逻辑会把敏感字段显示为 `[REDACTED_*]`。
- Agent 上报公网地址：源码不再写死真实域名，改为从 `NAT_WEBUI_PUBLIC_BASE_URL` 读取。
- 表单示例域名：使用 `node.example.com` 等占位示例。

### 按文件列出的脱敏位置

- `.gitignore`：忽略 `.env`、`.env.*`、`data/*.db`、`logs/*.log`、`.venv/`、`.test-venv*/`，避免环境变量、数据库、日志、测试环境进入仓库。
- `app/config.py`：只读取 `NAT_WEBUI_*` 环境变量，不保存生产密码；新增 `NAT_WEBUI_PUBLIC_BASE_URL` 作为 Agent 公网地址来源。
- `app/deployer.py`：部署生成脚本不再写死真实上报域名，改用 `PUBLIC_BASE_URL + AGENT_REPORT_PATH`；生成的 UUID、Reality key、short id 只写入运行数据库，不写入源码。
- `app/db.py`：展示/导出部署信息时对 `password`、`token`、`secret`、`private_key`、`vless://` 等字段做 `[REDACTED_*]` 处理。
- `app/templates/node-form.html`：节点 IP/域名输入框 placeholder 改为 `node.example.com`，不保留真实节点域名。
- `app/templates/nodes.html`、`app/templates/node-detail.html`：页面只展示数据库运行时内容；源码模板不内置真实节点、订阅 token 或 VLESS 链接。
- `scripts/run-prod.sh`：只加载本地 `.env.runtime`，脚本本身不写生产密码、真实 IP、真实域名或节点链接。
- `tests/test_app.py`：测试 IP 使用 `198.51.100.x`、`203.0.113.x` 文档保留地址；测试域名使用 `example.com`；测试密码是假值；测试 VLESS 链接是假 UUID + 保留地址。
- `README.md`：运行示例中的密码通过 `[hidden]` 展示；真实节点信息只用占位说明。
- `PROJECT_STATUS_HANDOFF.md`、`PHASE2.md`：作为文档一并扫描，要求不写真实节点 IP、真实域名、root 密码、token 或订阅链接。
- `data/`、`logs/`：仓库只保留 `.gitkeep`，真实数据库、缓存和日志都留在服务器本地。

### 上传前复查范围

上传 GitHub 前至少复查这些位置：

- `app/`：后端源码、部署脚本生成逻辑、配置读取、模板传参。
- `app/templates/`：页面 placeholder、错误提示、详情页展示内容。
- `scripts/`：启动脚本、辅助脚本，尤其避免写死 IP、域名、密码、token。
- `tests/`：测试数据只能使用保留 IP、示例域名、假 UUID、假密码。
- `README.md`、`PROJECT_STATUS_HANDOFF.md`、`PHASE2.md`：文档不得包含真实节点、域名、密码或订阅链接。

### 当前上传前扫描结论

最近一次上传前已做阻断级扫描：真实 IP、真实域名、root/sshpass、密码、token、API key、私钥、完整节点链接均未发现阻断项，结果为 `BLOCKING_FINDINGS 0`。

## 环境变量

运行期环境变量来自 `.env.runtime`，不要提交。

关键变量：

- `NAT_WEBUI_SESSION_SECRET`
- `NAT_WEBUI_ADMIN_USERNAME`
- `NAT_WEBUI_ADMIN_PASSWORD`
- `NAT_WEBUI_DB_PATH`
- `NAT_WEBUI_STATUS_STALE_MINUTES`
- `NAT_WEBUI_AGENT_REPORT_PATH`
- `NAT_WEBUI_PORT`（可选，默认 `8788`）
- `NAT_WEBUI_PUBLIC_BASE_URL`（可选，Agent 上报和订阅链接使用的外网地址）

开发占位默认密码只用于测试/无 env 场景。线上登录以 `.env.runtime` 为准。

## 目录结构与改动入口

- `app/main.py`
  - FastAPI 主入口
  - 登录、节点页面、节点 CRUD、订阅接口、部署入口、agent 上报入口
  - 常改位置：新增页面、表单提交、节点分类展示、订阅接口行为

- `app/db.py`
  - SQLite 数据访问层
  - 节点、标签、部署记录、订阅 token 等数据操作
  - 常改位置：节点字段、节点列表过滤、状态机、订阅筛选

- `app/deployer.py`
  - 直连节点部署逻辑
  - 负责 SSH 到目标机、合并同一 SSH 端点下的多个 inbound、写远端配置、启动 sing-box、回填各节点 VLESS 链接
  - 常改位置：Debian/Alpine 兼容、多 inbound 生成、Agent 上报脚本、回填字段、部署失败状态

- `app/chain_deployer.py`
  - 链式节点部署逻辑
  - 负责修改前置机 sing-box 配置：添加链式用户、后端 outbound、route rule
  - 常改位置：后端协议支持、outbound 生成、sing-box route 规则
  - 重要：sing-box 路由规则字段应使用 `user`，不是 `auth_user`

- `app/link_labels.py`
  - VLESS 链接 fragment / 国旗 / 节点名备注生成
  - 常改位置：地区识别、备注格式、链式节点出口国旗显示

- `app/regions.py`
  - 地区代码 / 国旗辅助逻辑

- `app/auth.py`
  - 登录校验与 session 逻辑

- `app/config.py`
  - 环境变量读取与默认值

- `app/templates/`
  - Jinja2 页面模板
  - `base.html`：整体布局、静态资源版本号
  - `nodes.html`：节点列表、三页签、订阅按钮
  - `node-form.html`：新建/编辑节点、链式/导入节点表单
  - `node-detail.html`：节点详情页
  - `deploy-detail.html`：部署详情页
  - `login.html`：登录页

- `app/static/style.css`
  - 主样式文件
  - 前端改完如遇缓存，更新 `app/templates/base.html` 里的 `style.css?v=...`

- `tests/test_app.py`
  - 当前主要测试入口
  - 覆盖登录、节点 CRUD、订阅、链式、导入节点、chain config 生成等

- `scripts/run-prod.sh`
  - foreground/systemd 启动脚本
  - 负责加载 `.env.runtime` 后启动 uvicorn
  - 端口可通过 `NAT_WEBUI_PORT` 环境变量自定义

- `scripts/start.sh`
  - nohup 后台启动脚本
  - 自动加载 `.env.runtime`、写 PID 文件

- `data/`
  - 运行期数据库、PID，不提交

- `logs/`
  - 运行日志，不提交

- `tmp/`
  - 临时文件，不提交

## 节点类型与职责

### 直连节点

`protocol_type = vless_reality_singbox`

用途：面板通过 SSH 部署并管理的 VLESS + Reality 节点。

可作为：

- 直连订阅节点
- 链式前置节点
- 链式后端/落地节点

相关入口：

- 新建：`GET/POST /nodes/new`
- 部署：`POST /nodes/{node_id}/reinstall`
- 订阅：`scope=direct` 或 `scope=all`

### 链式节点

`protocol_type = chain_vless_reality`

用途：客户端连接前置节点，前置节点按链式用户把流量转发到后端落地节点。

逻辑：

- 前置节点：必须是可管理的 `vless_reality_singbox`
- 后端节点：可以是 `vless_reality_singbox` 或 `imported_vless`
- 面板生成一个链式节点专用 UUID / 用户
- `chain_deployer.py` 在前置机 sing-box 配置里添加：
  - inbound users 中新增链式用户
  - outbounds 中新增后端 outbound
  - route.rules 中用 `user: [chain_tag]` 指向后端 outbound

相关入口：

- 新建：`GET/POST /nodes/new-chain`
- 部署/重部署：`POST /nodes/{node_id}/reinstall`
- 订阅：`scope=chain` 或 `scope=all`

### 仅导入节点

`protocol_type = imported_vless`

用途：用户不想交 SSH/root 密码，只粘贴现成 VLESS 链接。

限制：

- 不能作为链式前置节点
- 可以作为链式后端/落地节点
- 编辑时只允许改节点名、地区代码、地区显示名
- 不显示部署/重装按钮
- 不显示 Agent Token、部署信息、最近上报、最近部署记录
- 作为链式后端时，目前要求导入链接是 `VLESS + Reality + TCP`

相关入口：

- 新建：`GET/POST /nodes/new-import`
- 独立订阅：`scope=import`
- 链式后端候选：`list_chain_backend_nodes()` 包含它
- 链式前置候选：`list_direct_vless_nodes()` 不包含它

## 订阅接口

旧入口保留，避免客户端失效。

v2rayN：

- 全部：`/sub/{token}`
- 直连：`/sub/{token}?scope=direct`
- 链式：`/sub/{token}?scope=chain`
- 仅导入：`/sub/{token}?scope=import`

Clash：

- 全部：`/sub/{token}/clash`
- 直连：`/sub/{token}/clash?scope=direct`
- 链式：`/sub/{token}/clash?scope=chain`
- 仅导入：`/sub/{token}/clash?scope=import`

订阅筛选主要看 `app/db.py` 的 `list_subscribable_nodes(scope=...)`。

页面订阅按钮主要在 `app/templates/nodes.html`。

## 常见开发任务定位

### 改节点列表 UI

优先看：

- `app/templates/nodes.html`
- `app/static/style.css`
- `app/main.py` 的 `/nodes` route

改完记得：

- 更新 `base.html` 里的 CSS 版本号
- 登录后访问 `/nodes` 验证

### 改新建/编辑表单

优先看：

- `app/templates/node-form.html`
- `app/main.py` 的 `/nodes/new`、`/nodes/new-chain`、`/nodes/new-import`
- `app/main.py` 的 `/nodes/{node_id}/edit`

### 改订阅分类

优先看：

- `app/db.py`：`list_subscribable_nodes`
- `app/main.py`：`subscription_feed`、`clash_subscription_feed`
- `app/templates/nodes.html`：订阅按钮和 URL
- `tests/test_app.py`：订阅相关测试

### 改链式部署

优先看：

- `app/chain_deployer.py`
- `app/main.py`：链式节点创建、部署入口
- `app/db.py`：`list_direct_vless_nodes`、`list_chain_backend_nodes`
- `tests/test_app.py`：`test_build_front_chain_config_...`

关键约束：

- 仅导入节点不能做前置
- 仅导入节点只能做后端
- route rule 用 `user` 字段
- 不能把用户流量路由写成旧字段 `auth_user`

### 改直连节点部署

优先看：

- `app/deployer.py`
- `app/jobs.py`
- `app/main.py` 的 `/nodes/{node_id}/reinstall`
- 同一 `IP + SSH端口` 可存在多个直连节点，但 `公网端口` / `监听端口` 不能冲突
- `app/db.py` 的部署记录与状态更新函数

重装前必须释放目标监听端口：

- 先停止 systemd/OpenRC 管理的 `sing-box`
- 再检查 `listen_port` 是否仍被占用
- 若占用者是本项目残留的 `/usr/local/bin/sing-box run -c /etc/sing-box/config.json`，允许清理后继续
- 若占用者不是本项目 `sing-box`，必须报错并输出占用进程，不要误杀其他服务
- 判断 `systemctl` 时必须同时确认 `/run/systemd/system` 存在；部分 Alpine/LXC 环境可能残留 `systemctl` 命令但实际不是 systemd，不能误走 systemd 分支
- 写 systemd unit 前先创建 `/etc/systemd/system`，避免纯 Alpine 环境目录不存在导致部署脚本提前失败
- 启动后必须再次验证目标端口已监听

### 改节点状态逻辑

优先看：

- `app/db.py`
- `create_deployment_record`
- `mark_deployment_success`
- `mark_deployment_failed`
- `set_node_generated_fields`
- agent 上报相关函数

注意：已有可用链接或近期上报的节点，不应因为一次重装失败就被误判成永久不可用。

## 测试与验证

每次功能改完至少跑：

```bash
cd /opt/natxyz
python -m py_compile app/main.py app/db.py app/deployer.py app/chain_deployer.py
. .venv/bin/activate
PYTHONPATH=. pytest -q tests/test_app.py
```

当前基线：`32 passed`。

页面验证建议：

```bash
cd /opt/natxyz
. .venv/bin/activate
python - <<'PY'
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
r = c.post('/login', data={'username':'admin','password':'change-me-before-production'}, follow_redirects=False)
print('test-login-status', r.status_code)
PY
```

注意：上面是测试默认密码，只能证明测试环境逻辑，不代表生产登录密码。

生产页面验证应通过实际浏览器登录，或确认运行进程加载了 `.env.runtime`。

## Git / 提交规则

当前工作流：

```bash
cd /opt/natxyz
git status --short
git diff --stat
python -m py_compile app/main.py app/db.py app/deployer.py app/chain_deployer.py
. .venv/bin/activate && PYTHONPATH=. pytest -q tests/test_app.py
git add <changed files>
git commit -m "..."
git push origin main
```

不要提交：

- `.env.runtime`
- `data/*.db`
- `data/*.pid`
- `logs/*.out`
- `logs/*.err`
- 运行期临时文件

`.gitignore` 已包含这些运行产物。

## 最近关键状态

最近已完成并 push：

- 直连节点支持同一 VPS 多节点合并为多个 inbound
- 导入节点与批量导入入口已拆分，`/nodes#imported` 等页签返回已修复
- Agent 上报地址改为通过 `NAT_WEBUI_PUBLIC_BASE_URL` 配置，不在源码写死公网域名
- GitHub 上传前已补充脱敏清单并清理残留真实/疑似真实节点标记
- 测试：`32 passed`

## 下次接手最短路径

1. 进入运行目录：

```bash
cd /opt/natxyz
```

2. 看项目说明：

```bash
sed -n '1,260p' README.md
```

3. 看当前改动：

```bash
git status --short && git log -3 --oneline
```

4. 如果是 UI 问题，先看：

```bash
app/templates/nodes.html
app/templates/node-form.html
app/templates/node-detail.html
app/static/style.css
```

5. 如果是链式/导入节点问题，先看：

```bash
app/chain_deployer.py
app/db.py
app/main.py
tests/test_app.py
```

6. 改完跑测试、重启、再 push。
