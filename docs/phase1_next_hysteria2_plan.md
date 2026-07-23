# Phase 1 后续：Hysteria2 最小闭环实施计划

> 本计划衔接第一阶段“协议 registry + VLESS Reality handler”改造。目标是在不破坏现有 VLESS Reality、链式代理、导入节点、Cloudflare Tunnel 的前提下，先让 Nat xyz 出现第一个新增协议：Hysteria2。

## 1. 本阶段目标

实现 Hysteria2 的最小可用闭环：

- WebUI 可以选择 `Hysteria2` 协议。
- 创建/编辑节点时能保存 Hysteria2 必要参数。
- 部署器能生成 sing-box `hysteria2` inbound。
- 部署成功后能生成 `hy2://` 分享链接。
- 订阅接口能输出 Hysteria2 链接。
- 同一 VPS 多节点部署时，VLESS Reality 和 Hysteria2 可以合并到同一个 sing-box 配置。
- 现有链式代理继续只支持 VLESS Reality / imported VLESS，不在本阶段扩展。

## 2. 非目标

本阶段不做以下事情：

- 不支持 Hysteria2 作为链式后端。
- 不实现完整 Clash Hysteria2 YAML 转换。
- 不做 ACME 自动签证书。
- 不做复杂 obfs / bandwidth / masquerade 高级配置。
- 不迁移或删除旧字段 `last_vless_link`。
- 不直接执行或嵌入 fscarmen/sing-box.sh。

## 3. 兼容策略

为了降低线上风险，本阶段采用保守兼容：

- 继续使用 `last_vless_link` 存储订阅分享链接，字段名暂不改。
- Hysteria2 的密码优先复用 `generated_uuid` 字段存储，避免立刻新增复杂 schema。
- `generated_private_key`、`generated_public_key`、`generated_short_id` 对 Hysteria2 留空。
- `selected_reality_target` 对 Hysteria2 暂时作为 SNI / TLS server_name 使用。
- 订阅仍通过 `list_subscribable_nodes()` 读取 `last_vless_link`。

后续第二阶段再引入通用字段：

- `share_link`
- `protocol_params_json`
- `generated_materials_json`

## 4. 协议命名

新增协议常量：

```text
hysteria2
```

显示名称：

```text
Hysteria2
```

订阅标签：

```text
hy2
```

## 5. 数据保存设计

Hysteria2 节点继续使用现有 `nodes` 表字段：

- `protocol_type = 'hysteria2'`
- `ip`：公网 IP 或 DDNS
- `ssh_port`：SSH 端口
- `ssh_user`：SSH 用户
- `ssh_password`：SSH 密码
- `public_port`：客户端连接端口
- `listen_port`：远端 sing-box 监听端口
- `selected_reality_target`：暂用作 Hysteria2 SNI
- `generated_uuid`：暂用作 Hysteria2 password
- `last_vless_link`：暂用作 Hysteria2 分享链接

这种设计不是最终形态，但最小改动、最安全。

## 6. WebUI 改动

在普通节点表单的协议选择中增加：

```text
vless
hysteria2
tunnel
```

字段显示策略：

- VLESS Reality：显示 Reality 伪装目标说明。
- Hysteria2：显示公网端口、内网监听端口、SNI。
- Tunnel：显示应用路由域名、WS 端口、Tunnel token。

表单校验：

- `hysteria2` 使用普通部署节点必填字段。
- SNI 允许为空；为空时默认 `www.example.com`。
- IP / DDNS、端口校验沿用现有逻辑。

## 7. 部署器改动

新增文件：

```text
app/protocols/hysteria2.py
```

实现：

- `protocol_type = 'hysteria2'`
- `build_inbound()` 生成 sing-box Hysteria2 inbound。
- `build_share_link()` 生成 `hy2://` 链接。

sing-box inbound 第一版：

```json
{
  "type": "hysteria2",
  "tag": "hysteria2-node_id",
  "listen": "::",
  "listen_port": 443,
  "users": [{"password": "generated-password"}],
  "tls": {
    "enabled": true,
    "server_name": "www.example.com"
  }
}
```

注意：证书策略是本阶段最大风险点。第一版只完成配置生成和 WebUI 闭环；真实远端连接可在测试 VPS 上继续验证并决定是否加自签证书生成逻辑。

## 8. 分享链接设计

生成形式：

```text
hy2://password@host:port?sni=server_name#remark
```

要求：

- password 使用自动生成随机值。
- host 使用 `ip` 字段。
- port 使用 `public_port`。
- remark 使用地区规则生成。
- 测试中不得写真实节点链接。

## 9. 多节点合并部署

修改 `run_multi_real_deploy()` 相关流程：

- VLESS Reality：继续生成 UUID、Reality key、short_id。
- Hysteria2：生成 password，不生成 Reality key。
- `build_multi_singbox_config()` 根据 `protocol_type` 调用对应 handler。
- 每个节点部署结果写入对应分享链接。

## 10. 订阅设计

本阶段订阅不重构：

- 继续读取 `last_vless_link`。
- Hysteria2 部署后把 `hy2://` 写入 `last_vless_link`。
- v2rayN 订阅会同时输出 VLESS 和 Hysteria2 链接。
- Clash 订阅暂不保证 Hysteria2 完整转换。

## 11. 测试计划

新增或更新测试：

- 协议 registry 能找到 `hysteria2`。
- Hysteria2 handler 能生成 inbound。
- Hysteria2 handler 能生成 `hy2://` 分享链接。
- `clean_node_form()` 接受 `protocol_type=hysteria2`。
- VLESS Reality 既有配置生成测试不退化。
- 链式 `auth_user` 测试不退化。
- 订阅输出可以包含非 VLESS 链接。

## 12. 验收标准

本阶段完成标准：

- 页面协议下拉能看到 `Hysteria2`。
- 创建 Hysteria2 节点不会被后端拒绝。
- 生成的 sing-box config 中包含 `type: hysteria2` inbound。
- 部署结果能生成 `hy2://` 分享链接。
- 现有 `pytest` 通过。
- 不出现明文 SSH 密码、token、私钥、完整真实节点链接。

## 13. 风险和回滚

主要风险：

- Hysteria2 TLS 证书策略不完整，真实客户端连接可能失败。
- sing-box 不同版本对 Hysteria2 字段要求不同。
- 把 `last_vless_link` 临时复用为通用链接，命名不准确但兼容成本最低。

回滚方式：

- 删除 `hysteria2` 协议选项。
- 保留 `app/protocols/hysteria2.py` 也不会影响旧节点。
- 线上部署前必须备份 `/opt/natxyz`、数据库和 systemd 服务文件。
