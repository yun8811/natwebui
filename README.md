# NAT WebUI

轻量 NAT 节点管理面板。支持 VLESS Reality 节点管理（直连/链式/导入三种模式）、agent 状态上报、订阅链接分发。

## 快速部署（新 VPS）

```bash
git clone https://github.com/yun8811/natwebui.git /opt/natwebui
cd /opt/natwebui
bash scripts/install.sh
```

安装完成后，编辑 `app/deployer.py`，找到下面这行：

```python
report_url = f"http://YOUR_PANEL_IP:8788{AGENT_REPORT_PATH}"
```

把 `YOUR_PANEL_IP` 改成当前 VPS 的实际公网 IP。

```bash
bash scripts/run-prod.sh
```

面板默认监听 `0.0.0.0:8788`，用户名 `admin`，密码在安装时自动生成并打印在终端。

## 配置 systemd 开机自启

```bash
cat > /etc/systemd/system/nat-webui.service << 'SVC'
[Unit]
Description=NAT WebUI
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/natwebui
ExecStart=/opt/natwebui/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8788
EnvironmentFile=/opt/natwebui/.env.runtime
Restart=always

[Install]
WantedBy=multi-user.target
SVC

systemctl daemon-reload
systemctl enable --now nat-webui
```

## 环境变量

安装脚本会自动生成 `.env.runtime`，包含：

| 变量 | 说明 |
|------|------|
| `NAT_WEBUI_SESSION_SECRET` | 会话加密密钥（自动生成） |
| `NAT_WEBUI_ADMIN_USERNAME` | 管理员用户名（默认 admin） |
| `NAT_WEBUI_ADMIN_PASSWORD` | 管理员密码（自动生成） |
| `NAT_WEBUI_HOST` | 监听地址（默认 0.0.0.0） |
| `NAT_WEBUI_PORT` | 监听端口（默认 8788） |
| `NAT_WEBUI_DB_PATH` | 数据库路径（可选） |
| `NAT_WEBUI_STATUS_STALE_MINUTES` | 节点超时离线分钟数（可选） |
| `NAT_WEBUI_AGENT_REPORT_PATH` | agent 上报路径（可选） |

## 订阅使用

节点列表页顶部显示订阅 URL。将该 URL 粘贴到 v2rayN / NekoBox 等客户端的「订阅设置」中，通过「更新订阅」同步节点变更。

节点名称格式：`国旗 代号 | 自定义名称`，符合 v2rayN 展示习惯。

## 手动运行（不装 systemd）

```bash
cd /opt/natwebui
. .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8788
```

## 兼容性

- deployer 自动适配 Alpine（OpenRC）和 Debian/Ubuntu（systemd）
- 自动安装 sing-box、crontab 等依赖
- agent 每 5 分钟通过 crontab 上报在线状态

## 安全提醒

- `.env.runtime` 和 `data/*.db` 已在 `.gitignore` 中排除
- 部署到新 VPS 前请修改 `app/deployer.py` 中的 `YOUR_PANEL_IP`
- 生产环境建议配置防火墙仅开放 8788 端口
