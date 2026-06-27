# NAT WebUI 项目交接简报

更新时间：2026-06-02

## 项目定位

这是一个轻量 NAT / 家宽节点管理面板，用来集中管理节点信息、部署 VLESS Reality、展示节点状态，并生成客户端可导入的订阅链接。

当前主要服务对象：用户自建 NAT 小鸡、家宽落地机、前置中转机，以及“前置入口 -> 后端落地”的链式节点。

## 当前运行状态

- 本地正在运行的服务目录：`/root/.nanobot/workspace/nat-webui-project`
- 当前运行端口：`8788`
- 启动方式：`uvicorn app.main:app --host 0.0.0.0 --port 8788`
- 运行期环境变量文件：`.env.runtime`
- 数据库：`data/nat-webui.db`
- 当前进程 PID 文件：`data/uvicorn.pid`
- 日志文件：`logs/uvicorn.out`、`logs/uvicorn.err`

注意：GitHub 仓库目录是 `/root/local/projects/github/natxyz`，但用户当前看到的实际页面来自 `/root/.nanobot/workspace/nat-webui-project`。后续改功能时要确认同步到实际运行目录并重启服务。

## GitHub / 本地代码状态

- GitHub 仓库：`wk8326-ux/natxyz`
- GitHub main 已推送的最近功能提交：`97ee0f0 feat: split node tabs and subscription feeds`
- 运行目录当前还有本地修改，包含最近前端 tabs / 订阅拆分同步，以及部署相关未整理改动。
- 如果后续继续开发，先执行：

```bash
cd /root/.nanobot/workspace/nat-webui-project
git status --short
git diff --stat
```

确认本地改动后再决定是否整理提交或同步到 GitHub。

## 目录结构

- `app/main.py`
  - FastAPI 主入口
  - 登录、节点页面、节点 CRUD、订阅接口、部署入口、agent 上报入口

- `app/db.py`
  - SQLite 数据访问层
  - 节点、标签、部署记录、订阅 token 等数据操作

- `app/deployer.py`
  - 单节点部署逻辑
  - 负责 SSH 到目标机器，安装/配置 VLESS Reality、回填链接等

- `app/chain_deployer.py`
  - 链式节点前置机配置逻辑
  - 负责修改前置 sing-box 配置，把某个链式用户路由到后端 outbound

- `app/templates/`
  - Jinja2 页面模板
  - `nodes.html` 是节点列表页，已拆分为“直连 / 链式”标签页

- `app/static/`
  - CSS、图标、国旗等静态资源
  - `style.css` 已加入节点 tabs 和简洁订阅按钮样式

- `tests/`
  - pytest 测试
  - 当前运行目录测试已通过：`24 passed`

- `data/`
  - 运行期数据库、PID 等，不应提交

- `logs/`
  - 运行日志，不应提交

## 当前已完成能力

- 管理员登录
- 节点新增、编辑、删除
- 节点详情页
- 单节点部署 / 重装
- 节点名内联编辑
- 节点标签管理
- 节点表格前端排序
- 国旗 / 地区显示
- VLESS 链接复制
- v2rayN / Clash 订阅生成
- 链式节点展示
- 链式节点新建
- 直连 / 链式节点分标签页展示
- 订阅拆分为：
  - 全部订阅
  - 直连订阅
  - 链式订阅

## 订阅接口状态

旧订阅入口保留，避免已导入客户端失效。

- 全部 v2rayN：`/sub/{token}`
- 直连 v2rayN：`/sub/{token}?scope=direct`
- 链式 v2rayN：`/sub/{token}?scope=chain`
- 全部 Clash：`/sub/{token}/clash`
- 直连 Clash：`/sub/{token}/clash?scope=direct`
- 链式 Clash：`/sub/{token}/clash?scope=chain`

页面按钮保持简洁：每组只放 v2rayN 图标按钮和 Clash 图标按钮。

## 最近关键进展

1. 节点列表已按类型拆分：
   - `直连节点`
   - `链式节点`

2. 订阅已按类型拆分：
   - `scope=direct`
   - `scope=chain`
   - 默认不带 scope 为全部

3. 本地运行服务已同步该功能并重启。

4. 用户已确认新前端可见。

5. `RCN US家宽` 曾显示部署失败，但用户确认原因是商家更换 IP 未通知，不是项目 bug。当前不需要继续修部署判定。

6. 单节点重装已修复端口释放逻辑：部署脚本会先停止 systemd/OpenRC 的 `sing-box`，再清理本项目残留的 `/usr/local/bin/sing-box run -c /etc/sing-box/config.json` 进程；若监听端口被非本项目进程占用，会报错并输出占用者，避免误杀。

7. `老站hinet` 部署失败原因已确认：目标是 Alpine/OpenRC/LXC，存在 `systemctl` 命令但并非 systemd，且 `/etc/systemd/system` 目录缺失；旧脚本会提前写 systemd unit 并误判 init 系统。已修为创建 `/etc/systemd/system`，并仅在 `/run/systemd/system` 存在时走 systemd 分支，否则走 OpenRC。修复后该节点 `40482/tcp` 已监听且外部 TCP 已通。

## 链式节点重要背景

链式节点是：客户端连接前置机，前置机再转发到后端落地节点。

当前链式实现核心：

- 前置节点：sing-box Reality VLESS inbound
- 后端节点：目前主要支持 VLESS Reality 后端
- 面板为链式节点生成独立 UUID / 用户
- `chain_deployer.py` 会在前置 sing-box 配置中：
  - 添加链式用户
  - 添加后端 outbound
  - 添加路由规则，把该用户流量转发到对应 outbound

已定位过一个关键问题：sing-box 路由规则应使用 `user` 字段，不是 `auth_user`。这类问题记录在 `PHASE4_STEP6_RESULT.md`。

## 后续注意事项

- 改功能前先确认实际运行目录，不要只改 GitHub clone。
- 改完后要：

```bash
cd /root/.nanobot/workspace/nat-webui-project
. .venv/bin/activate
PYTHONPATH=. pytest -q
```

- 重启本地服务后再验证页面：

```bash
cd /root/.nanobot/workspace/nat-webui-project
kill -TERM $(cat data/uvicorn.pid) 2>/dev/null || true
set -a; . ./.env.runtime; set +a
nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8788 > logs/uvicorn.out 2> logs/uvicorn.err & echo $! > data/uvicorn.pid
```

- 涉及 CSS / 前端静态资源时，记得更新 `app/templates/base.html` 里的 `style.css?v=...`，避免用户看到旧缓存。

- 不要把 `.env.runtime`、数据库、日志、PID 文件提交到 GitHub。

## 新对话继续点

如果后续新开对话，优先从这里继续：

1. 进入实际运行目录：`/root/.nanobot/workspace/nat-webui-project`
2. 查看当前本地改动：`git status --short && git diff --stat`
3. 确认页面/订阅是否正常：检查 `/nodes` 是否有“直连节点 / 链式节点”，订阅链接是否带 `scope=direct` 和 `scope=chain`
4. 若继续开发，再决定是否把运行目录改动整理同步到 GitHub 仓库 `/root/local/projects/github/natxyz`
