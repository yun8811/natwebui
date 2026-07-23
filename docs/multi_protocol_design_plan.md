# Nat xyz 多协议扩展设计计划

> 目标：把 fscarmen/sing-box.sh 中成熟的多协议能力，按 Nat xyz 现有 WebUI / 数据库 / 部署器 / 订阅体系重新设计并逐步移植。本文只做设计计划，不直接执行实现。

## 1. 背景

Nat xyz 当前主要围绕以下能力构建：

- 直连节点：`vless_reality_singbox`
- 链式节点：`vless_chain`
- Cloudflare Tunnel 节点：`cf_vless_ws`
- 导入节点：`imported_vless`
- 订阅输出：v2rayNG / sing-box(NekoBox) / Clash
- 远端部署：通过 SSH 在目标 VPS 上生成 `/etc/sing-box/config.json` 并管理 `sing-box.service`
- 节点状态：通过 `/agent/report` 主动上报

用户反馈：当前协议太少，希望融合 `fscarmen/sing-box.sh` 的多协议能力。

fscarmen 脚本支持协议很多，包括：

- `XTLS + reality`
- `hysteria2`
- `tuic`
- `ShadowTLS`
- `shadowsocks`
- `trojan`
- `vmess + ws`
- `vless + ws + tls`
- `H2 + reality`
- `gRPC + reality`
- `AnyTLS`
- `naive`

但该脚本是系统级交互式一键脚本，会直接改 `/etc/sing-box`、systemd、防火墙、订阅模板，并可能调用其他远程脚本，因此不适合直接嵌入或直接由 Nat xyz 调用。

正确路线是：保留 Nat xyz 的产品架构，把 fscarmen 脚本作为协议模板和运维经验参考，逐步把协议配置生成、链接生成、订阅转换、部署检查移植成 Nat xyz 内部模块。

## 2. 设计目标

### 2.1 功能目标

- 在 Nat xyz 中支持更多 sing-box 入站协议。
- 所有新增协议都能通过 WebUI 创建、编辑、部署、重装、删除。
- 所有新增协议都能进入订阅输出，至少支持 v2rayNG 和 sing-box/NekoBox，逐步支持 Clash。
- 保留现有 VLESS Reality、链式代理、导入节点、Cloudflare Tunnel 能力。
- 保持远端部署仍由 Nat xyz 管理，而不是交给外部脚本接管。
- 支持同一台 VPS 上多个协议节点共存，统一生成一个 sing-box 配置。

### 2.2 工程目标

- 不把 fscarmen 的大脚本整段塞进项目。
- 不直接执行远程 `bash <(wget ...)`。
- 协议配置生成逻辑模块化、可测试。
- 数据库存储从“VLESS 专用字段”逐步演进到“协议通用字段 + 协议参数 JSON”。
- 尽量兼容旧数据库和旧节点，不破坏已有线上数据。
- 每个协议都要有单元测试覆盖配置生成、链接生成、订阅输出、表单校验。

### 2.3 非目标

- 第一阶段不做完整 fscarmen 脚本所有功能一比一复刻。
- 第一阶段不支持自动安装 Cloudflare Argo、WARP 打洞、TCP 优化脚本等外部功能。
- 第一阶段不做复杂的多用户套餐/计费系统。
- 第一阶段不做所有客户端格式的完美兼容，但已针对 Hysteria2 区分 v2rayNG 与 sing-box/NekoBox 订阅。
- 不保存或展示明文敏感链接到公开文档或 GitHub。

## 3. 当前架构现状

### 3.1 数据库

核心表是 `nodes`，当前字段明显偏 VLESS Reality：

- `protocol_type`
- `public_port`
- `listen_port`
- `selected_reality_target`
- `generated_uuid`
- `generated_private_key`
- `generated_public_key`
- `generated_short_id`
- `last_vless_link`
- `cf_host`
- `cf_tunnel_token`
- `ws_port`
- `ws_path`
- `front_node_id`
- `backend_node_id`
- `chain_mode`

问题：

- `last_vless_link` 名称已经不适合多协议。
- Reality key 字段不适合 Hysteria2 / TUIC / Trojan / Shadowsocks。
- 节点参数散落在表字段中，后续协议越多字段越膨胀。

### 3.2 部署器

主要文件：`app/deployer.py`

当前能力：

- 通过 `RemoteExecutor` 使用 SSH 执行远端脚本。
- 获取 sing-box release。
- 生成 VLESS Reality sing-box config。
- 生成 Cloudflare Tunnel VLESS WS config。
- 生成 agent report 脚本。
- 支持同 SSH endpoint 的多个直连节点合并部署。

问题：

- `build_multi_singbox_config()` 当前主要面向 VLESS Reality。
- 返回对象 `DeployResult` / `DeployedNodeResult` 字段也偏 VLESS，例如 `generated_vless_link`。
- 远端配置生成没有协议注册机制。

### 3.3 WebUI

主要文件：

- `app/main.py`
- `app/templates/node-form.html`
- `app/templates/nodes.html`
- `app/templates/node-detail.html`

当前表单只支持：

- `vless`
- `tunnel`
- `imported_vless`
- `chain`

问题：

- 协议选择写死在模板和后端判断里。
- 表单字段以 VLESS Reality 为主。
- 新增协议会让模板条件分支越来越复杂。

### 3.4 订阅

当前订阅主要依赖 `last_vless_link`。

问题：

- 多协议后不能只看 `last_vless_link`。
- v2rayNG、sing-box/NekoBox、Clash 对不同协议字段要求不同。
- `scope=direct/chain/imported/all` 仍可保留，但协议类型需要细分。

## 4. 总体方案

### 4.1 核心原则

Nat xyz 不融合“脚本本体”，只融合“协议能力”。

具体来说：

- fscarmen 脚本负责提供参考：协议字段、sing-box 配置结构、客户端链接格式、安装经验。
- Nat xyz 负责实现：数据库、WebUI、部署器、订阅、测试、状态管理。

### 4.2 新模块建议

建议新增目录：

```text
app/protocols/
  __init__.py
  registry.py
  models.py
  vless_reality.py
  hysteria2.py
  tuic.py
  trojan.py
  shadowsocks.py
  vmess_ws.py
  vless_ws_tls.py
  validators.py
  subscriptions.py
```

模块职责：

- `registry.py`：协议注册表，定义支持哪些协议。
- `models.py`：协议通用 dataclass / TypedDict。
- `validators.py`：端口、域名、密码、UUID、路径校验。
- 单协议文件：生成 sing-box inbound、生成分享链接、定义表单字段、定义默认值。
- `subscriptions.py`：多协议订阅输出转换。

### 4.3 协议注册接口

建议每个协议实现统一接口：

```python
class ProtocolHandler:
    protocol_type: str
    display_name: str
    category: str
    supports_deploy: bool
    supports_subscription: bool
    supports_chain_backend: bool

    def default_params(self) -> dict: ...
    def validate_params(self, node: dict) -> list[str]: ...
    def generate_materials(self, node: dict) -> dict: ...
    def build_inbound(self, node: dict, materials: dict) -> dict: ...
    def build_share_link(self, node: dict, materials: dict) -> str: ...
    def to_clash_proxy(self, node: dict, link: str) -> dict | None: ...
```

这样新增协议只需要新增 handler，不需要到处改 if/else。

## 5. 数据库设计

### 5.1 新增字段

为了兼容旧表，建议先增量迁移，不立刻重构整张表。

新增字段：

```sql
ALTER TABLE nodes ADD COLUMN share_link TEXT;
ALTER TABLE nodes ADD COLUMN protocol_params_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE nodes ADD COLUMN generated_materials_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE nodes ADD COLUMN subscription_tags_json TEXT NOT NULL DEFAULT '[]';
```

字段说明：

- `share_link`：通用分享链接，替代 `last_vless_link`。
- `protocol_params_json`：协议参数，例如密码、路径、TLS、混淆、SNI、ALPN。
- `generated_materials_json`：自动生成材料，例如 UUID、Reality key、short_id、TUIC password。
- `subscription_tags_json`：订阅分类和客户端附加信息。

### 5.2 保留旧字段

为了兼容旧代码和旧数据，暂时保留：

- `last_vless_link`
- `generated_uuid`
- `generated_private_key`
- `generated_public_key`
- `generated_short_id`

兼容策略：

- VLESS Reality 部署后同时写 `share_link` 和 `last_vless_link`。
- 订阅读取时优先 `share_link`，为空时回退 `last_vless_link`。
- 旧导入节点仍支持 `imported_vless`。

### 5.3 协议类型命名

建议规范化：

```text
vless_reality
hysteria2
tuic_v5
trojan_tls
shadowsocks_2022
vmess_ws
vless_ws_tls
h2_reality
grpc_reality
anytls
naive
cf_vless_ws
imported_vless
vless_chain
```

兼容旧值：

```text
vless_reality_singbox -> vless_reality
```

短期可以保留旧值不改名，新增 handler 注册别名。

## 6. 第一阶段协议优先级

### 6.1 第一批推荐落地

优先新增：

```text
hysteria2
tuic_v5
trojan_tls
shadowsocks_2022
```

原因：

- 和现有 VLESS Reality 互补明显。
- 都是 sing-box 原生支持的常用协议。
- 不强依赖复杂反代。
- 适合 NAT VPS 多端口部署。

### 6.2 第二批

```text
vmess_ws
vless_ws_tls
grpc_reality
h2_reality
```

原因：

- 需要更多 TLS / WebSocket / HTTP2 / gRPC 参数。
- 和域名、证书、反代关系更复杂。
- UI 表单复杂度更高。

### 6.3 第三批

```text
anytls
naive
ShadowTLS
```

原因：

- 客户端兼容性、配置差异、订阅转换风险更高。
- 适合在核心多协议架构稳定后再做。

## 7. 协议配置设计

### 7.1 VLESS Reality

现状已有，后续迁移为 handler。

需要保留：

- UUID
- Reality private/public key
- short_id
- flow: `xtls-rprx-vision`
- server_name / handshake server

sing-box inbound 核心：

```json
{
  "type": "vless",
  "tag": "vless-reality-node",
  "listen": "::",
  "listen_port": 443,
  "users": [{"uuid": "...", "flow": "xtls-rprx-vision"}],
  "tls": {
    "enabled": true,
    "server_name": "example.org",
    "reality": {
      "enabled": true,
      "handshake": {"server": "example.org", "server_port": 443},
      "private_key": "...",
      "short_id": ["..."]
    }
  }
}
```

### 7.2 Hysteria2

建议字段：

- `listen_port`
- `public_port`
- `password`
- `obfs_enabled`
- `obfs_password`
- `tls_mode`: `self_signed` / `acme` / `manual`
- `sni`
- `alpn`
- `bandwidth_up`
- `bandwidth_down`

第一版建议：

- 只做 password auth。
- 默认自签证书或 Reality 无关普通 TLS。
- 暂不做 Realm / WARP 打洞。

sing-box inbound 方向：

```json
{
  "type": "hysteria2",
  "tag": "hy2-node",
  "listen": "::",
  "listen_port": 443,
  "users": [{"password": "..."}],
  "tls": {"enabled": true, "server_name": "example.org"}
}
```

风险：

- 证书策略必须明确，否则客户端可能无法连。
- UDP 转发、防火墙放行必须处理。

### 7.3 TUIC v5

建议字段：

- `listen_port`
- `public_port`
- `uuid`
- `password`
- `sni`
- `congestion_control`
- `udp_relay_mode`
- `zero_rtt_handshake`
- `tls_mode`

第一版建议：

- 默认生成 UUID + password。
- 默认 congestion control 使用 `bbr` 或 `cubic`。
- 暂不开放过多高级项。

风险：

- 客户端 URI 格式差异较多。
- UDP 端口放行必须测试。

### 7.4 Trojan TLS

建议字段：

- `listen_port`
- `public_port`
- `password`
- `sni`
- `tls_mode`
- `fallback_enabled`

第一版建议：

- password 自动生成。
- TLS 使用与 Hysteria2 相同证书策略。
- 暂不做复杂 fallback。

### 7.5 Shadowsocks 2022

建议字段：

- `listen_port`
- `public_port`
- `method`
- `password`
- `plugin`

第一版建议支持方法：

```text
2022-blake3-aes-128-gcm
2022-blake3-aes-256-gcm
2022-blake3-chacha20-poly1305
```

风险：

- 不同客户端对 2022 方法支持不一致。
- 可提供传统 AEAD 方法作为兼容选项，但默认推荐 2022。

## 8. 远端部署设计

### 8.1 单机多协议合并配置

当前 Nat xyz 已有同 SSH endpoint 多 VLESS inbound 的思路。

多协议后应扩展为：

- 查询同一 `ip + ssh_port + ssh_user` 下所有可部署节点。
- 按每个节点的 `protocol_type` 找 handler。
- handler 生成 inbound。
- 合并所有 inbound 到一个 `/etc/sing-box/config.json`。
- outbounds 默认保留 `direct`。
- 链式节点需要额外 route rules。

### 8.2 端口冲突检查

新增协议后，重复校验从“VLESS 专用”变为“部署端口通用”。

规则：

- 同一 SSH endpoint 下，不允许两个部署型节点使用同一个 `listen_port`。
- 同一公网 IP/DDNS 下，不允许两个部署型节点使用同一个 `public_port`，除非协议明确支持复用。
- TCP 和 UDP 端口协议可在 UI 中显示，但第一版建议保守禁止复用。

### 8.3 防火墙

fscarmen 脚本有防火墙保存/恢复逻辑，Nat xyz 可以借鉴，但要简化。

第一版策略：

- 只开放当前 sing-box 配置涉及端口。
- 不主动清理用户已有规则。
- 记录 Nat xyz 管理过的端口到 `/opt/natctl/state/managed_ports.json`。
- 更新时只调整 Nat xyz 管理范围内的端口。

### 8.4 systemd

继续使用现有服务管理方式：

- 下载 sing-box 到 `/opt/natctl/bin` 或 `/etc/sing-box` 现有路径。
- 写入 `/etc/sing-box/config.json`。
- `sing-box check -c /etc/sing-box/config.json` 通过后再重启。
- 失败时保留旧配置并回滚。

建议新增流程：

1. 生成新配置到临时文件。
2. 远端执行 `sing-box check`。
3. 备份旧配置。
4. 原子替换配置。
5. 重启服务。
6. 检查服务状态。
7. 写部署结果和每个节点 share link。

## 9. WebUI 设计

### 9.1 表单拆分

当前 `node-form.html` 条件逻辑会越来越复杂。

建议拆分：

```text
app/templates/node-form.html
app/templates/partials/protocol_vless_reality.html
app/templates/partials/protocol_hysteria2.html
app/templates/partials/protocol_tuic.html
app/templates/partials/protocol_trojan.html
app/templates/partials/protocol_shadowsocks.html
app/templates/partials/protocol_tunnel.html
app/templates/partials/protocol_import.html
app/templates/partials/protocol_chain.html
```

### 9.2 协议选择 UI

新增协议选择：

```text
VLESS Reality
Hysteria2
TUIC v5
Trojan TLS
Shadowsocks 2022
Cloudflare Tunnel
```

链式节点和导入节点仍独立入口，不混在普通部署协议中。

### 9.3 高级选项

每个协议表单分为：

- 基础字段：节点名、IP/DDNS、SSH、端口。
- 协议字段：密码、UUID、SNI、TLS、method 等。
- 高级字段：ALPN、obfs、bandwidth、congestion。

第一版高级字段默认隐藏，避免普通用户被吓到。

## 10. API 和后端路由设计

当前创建/编辑逻辑集中在 `app/main.py`。

建议新增服务层：

```text
app/node_service.py
app/protocols/registry.py
```

职责：

- 表单数据标准化。
- 调用协议 handler 校验。
- 写入 `protocol_params_json`。
- 兼容旧字段。
- 统一返回错误。

后端路由保持 URL 不变：

- `GET /nodes/new`
- `POST /nodes/new`
- `GET /nodes/{node_id}/edit`
- `POST /nodes/{node_id}/edit`
- `POST /nodes/{node_id}/reinstall`

这样前端链接和旧测试不需要大改。

## 11. 订阅设计

### 11.1 v2rayNG 与 sing-box/NekoBox 订阅

优先保证每个节点有一个标准 share link，同时允许按客户端生成不同参数的订阅链接。

读取规则：

1. 优先读取 `share_link`。
2. 兼容读取 `last_vless_link`。
3. 按地区和节点名重写 remark。
4. Base64 打包输出。
5. `client=xray` 用于 v2rayNG/Xray 兼容订阅；默认订阅用于 sing-box/NekoBox。

Hysteria2 当前兼容策略：

- sing-box / NekoBox 默认订阅保留 `insecure=1`、`pinSHA256`、`pinnedPeerCertSha256`、`verifyPeerCertByName`，兼容已验证可用的 sing-box 内核客户端。
- v2rayNG 专用订阅使用 `pinSHA256=<证书 DER SHA256>`，移除 `insecure`、`pinnedPeerCertSha256`、`verifyPeerCertByName`。
- 原因是 v2rayNG 的 Hysteria2 URI 解析只读取 `pinSHA256` 并映射到 Xray 的 `pinnedCA256`，不会读取 `pinnedPeerCertSha256` 或 `verifyPeerCertByName`。

### 11.2 Clash 订阅

不同协议需要生成不同 proxy YAML。

建议由 handler 提供：

```python
def to_clash_proxy(node: dict, materials: dict) -> dict | None:
    ...
```

不能可靠转换的协议，第一版可以：

- 在 Clash 订阅中跳过。
- UI 标注“仅 v2rayN 支持”。
- 后续再补 Clash 支持。

### 11.3 Scope 保持兼容

保留现有 scope：

```text
all
direct
chain
imported
```

新增协议仍属于 `direct` 类部署型节点。

建议新增可选协议过滤：

```text
/sub/{token}/v2rayn?scope=direct&protocol=hysteria2&client=xray
/sub/{token}/clash?scope=direct&protocol=tuic_v5
```

## 12. 链式代理兼容设计

当前链式代理基于：

- 前置节点：VLESS Reality
- 后端节点：VLESS Reality 或 imported VLESS
- route rule 使用 `auth_user`

多协议后建议分阶段：

第一阶段：

- 链式前置仍只支持 VLESS Reality。
- 链式后端仍只支持 VLESS Reality / imported VLESS。
- 不把 Hysteria2 / TUIC / Trojan 立即纳入链式后端。

第二阶段：

- 支持更多 outbound 类型作为链式后端。
- handler 提供 `build_outbound()`。
- 链式后端不再只解析 VLESS link。

原因：

- 链式路由已经是高风险功能。
- 先稳定多协议直连，再扩展链式，避免同时引入太多变量。

## 13. 迁移计划

### Phase 0：设计和测试基线（已完成）

- 新增本文档。
- 跑现有测试，确认基线。
- 增加 protocol registry 的空框架测试。

验收：

- 当前功能无变化。
- `pytest` 通过。

### Phase 1：协议注册框架（已完成）

- 新增 `app/protocols/`。
- 把现有 VLESS Reality 迁入 handler。
- 保持旧 API、旧 UI、旧数据不变。
- `build_multi_singbox_config()` 改为调用 handler。

验收：

- 现有 VLESS Reality 部署生成配置与旧版本等价。
- 链式 `auth_user` 测试继续通过。
- 订阅输出不变。

### Phase 2：数据库通用字段

- 添加 `share_link`。
- 添加 `protocol_params_json`。
- 添加 `generated_materials_json`。
- 写迁移和回退兼容。
- 订阅读取优先使用 `share_link`。

验收：

- 旧节点不需要手工迁移即可显示和订阅。
- 新部署 VLESS 同时写新旧字段。

### Phase 3：新增 Hysteria2（已完成）

- 实现 `hysteria2.py` handler。
- 增加表单 partial。
- 增加配置生成测试。
- 增加分享链接测试。
- 增加部署端口校验。
- 修复自签证书 SAN 生成，避免客户端报 `legacy Common Name field`。
- 面板订阅按钮拆分为 v2rayNG、sing-box/NekoBox、Clash。
- 为 v2rayNG 增加 `client=xray` 专用订阅输出，最终验证 HY2 可用。

验收：

- 能创建 Hysteria2 节点。
- 能生成 sing-box inbound。
- 能生成 v2rayNG 与 sing-box/NekoBox 可导入链接。
- 不影响 VLESS Reality。

### Phase 4：Hysteria2 + Reality（下一阶段）

目标：

- 研究 sing-box / fscarmen 对 Hysteria2 + Reality 或类 Reality 前置伪装方案的实际支持边界。
- 不凭概念实现，先确认 sing-box 官方配置能力、客户端支持情况和 fscarmen 脚本现有做法。
- 在不破坏当前 Hysteria2 自签证书 + v2rayNG/NekoBox 可用配置的前提下，新增独立实验模式。
- 如果 sing-box 原生不支持 HY2 直接叠加 Reality，则改为设计等价替代方案，例如 Hysteria2 + SNI/证书伪装、端口跳跃、Realm/WARP-assisted Realm 或前置转发。

验收：

- 有源码或官方文档依据说明 HY2 + Reality 是否可直接实现。
- 若可实现：新增配置生成、分享链接、订阅、部署和客户端测试。
- 若不可直接实现：输出可落地替代方案并保留当前 HY2 稳定链路。
- 当前 v2rayNG、NekoBox/sing-box、Clash 订阅不退化。

### Phase 5：订阅和 Clash 完善

- 为每个协议补 Clash proxy 生成。
- UI 标注协议客户端兼容性。
- 增加协议过滤参数。

### Phase 6：链式后端扩展

- handler 增加 `build_outbound()`。
- 链式后端支持更多协议。
- 保留 `auth_user` 路由规则。

## 14. 测试计划

### 14.1 单元测试

新增测试类型：

- 协议注册表测试。
- 每个协议默认参数测试。
- 每个协议参数校验测试。
- 每个协议 sing-box inbound 生成测试。
- 每个协议 share link 生成测试。
- 订阅输出测试。
- 多协议合并配置测试。
- 端口冲突测试。

### 14.2 集成测试

建议新增：

- 创建 Hysteria2 节点 → 查看详情 → 生成部署任务。
- 创建 Trojan 节点 → 生成 v2rayNG / sing-box 订阅。
- 同 SSH endpoint 创建 VLESS + Hysteria2 → 合并配置中存在两个 inbound。
- 删除一个节点后重新部署 → 配置中移除对应 inbound。

### 14.3 远端验证

每个协议上线前在测试 VPS 验证：

- `sing-box check` 通过。
- `systemctl restart sing-box` 成功。
- 端口监听正确。
- 客户端可以导入链接。
- 实际连接出口正确。
- agent 状态仍会上报。

## 15. 当前实现进度（2026-07-02）

已完成：

- 协议注册框架已落地到 `app/protocols/`。
- Hysteria2 最小闭环已完成：创建、部署、订阅、Clash 转换、远端校验。
- Hysteria2 自签证书已改为带 SAN，默认 SNI/CN/SAN 为 `www.nvidia.com`。
- NekoBox / sing-box 客户端已验证可用。
- v2rayNG 客户端已验证可用，关键参数为 `pinSHA256=<证书 DER SHA256>`。
- 面板 `/nodes` 的订阅按钮已拆分为 v2rayNG、sing-box/NekoBox、Clash，避免不同客户端参数互相污染。
- 线上与本地测试均保持通过，当前基线为 `42 passed`。

后续优先级：

1. 第一阶段暂时收尾，冻结当前 Hysteria2 可用基线。
2. 下一阶段优先研究并实现 `Hysteria2 + Reality` 或经验证的等价替代方案。
3. 在动手前先查 sing-box 官方配置、fscarmen 脚本实现和主流客户端支持，避免凭概念硬做。
4. 保持 Hysteria2 不作为链式后端，先稳定直连协议。
5. Trojan TLS、Shadowsocks 2022、TUIC v5 后移到 HY2 + Reality 方案之后。
6. 数据库通用字段仍建议后移，避免在协议扩展早期破坏现有线上数据。

## 16. 安全设计

### 15.1 不执行远程一键脚本

Nat xyz 不应在生产逻辑中执行：

```text
bash <(wget ...)
```

原因：

- 不可审计。
- 容易覆盖已有配置。
- 行为随上游脚本变化。
- 难以做回滚和测试。

### 15.2 敏感信息处理

敏感信息包括：

- SSH 密码
- Tunnel token
- 节点完整分享链接
- UUID / password / private key
- 订阅 token

要求：

- 日志中只输出脱敏信息。
- GitHub 文档和测试不出现真实密钥。
- 部署 raw log 需要经过 `redact_sensitive_text()`。
- UI 显示敏感字段默认隐藏。

### 15.3 配置回滚

远端部署必须：

- 写配置前备份旧配置。
- 新配置通过 `sing-box check` 后再替换。
- 重启失败时回滚旧配置。
- raw log 记录失败阶段。

### 15.4 防火墙安全

- 只管理 Nat xyz 创建的端口。
- 不清空用户已有防火墙规则。
- UDP 协议要明确提示需要放行 UDP。
- 删除节点时不要误删其他节点正在使用的端口。

## 17. 风险清单

### 高风险

- 多协议合并配置覆盖现有 sing-box 配置。
- 新协议端口冲突导致旧节点不可用。
- 订阅链接格式不兼容客户端。
- 日志泄露节点密码或 token。
- 链式代理扩展时破坏现有 `auth_user` 路由。

### 中风险

- SQLite 字段继续膨胀，维护困难。
- UI 表单复杂度过高。
- Clash 对部分协议支持不完整。
- 不同 sing-box 版本配置字段变化。

### 低风险

- 协议显示名称、图标、说明文案不完善。
- 高级字段默认值需要多轮调优。

## 18. 验收标准

第一阶段总体验收：

- 旧 VLESS Reality 节点创建、部署、订阅不退化。
- 链式代理仍使用 `auth_user`，测试覆盖不丢失。
- 新增 Hysteria2 至少可完成创建、配置生成、链接生成、订阅输出。
- 数据库迁移不破坏旧数据。
- 敏感扫描无真实密码、token、私钥、完整节点链接。
- pytest 全部通过。

完整多协议验收：

- 支持至少 5 种直连协议：VLESS Reality、Hysteria2、TUIC、Trojan、Shadowsocks。
- 同一 VPS 可以部署多个不同协议节点。
- 每个节点详情页显示协议、端口、状态、订阅支持情况。
- v2rayNG / sing-box 订阅包含所有支持协议。
- Clash 订阅至少支持 VLESS Reality、Trojan、Shadowsocks，其他协议明确标注支持状态。
- 远端部署失败可回滚，不影响旧节点运行。

## 19. 推荐实施顺序

最推荐的实际开发顺序：

1. 新增 `docs/multi_protocol_design_plan.md`。
2. 新增协议注册框架，但不改变行为。
3. 把 VLESS Reality 迁到 handler，跑全量测试。
4. 添加 `share_link` 和 JSON 参数字段，保持兼容。
5. 新增 Hysteria2，完成最小闭环。（已完成）
6. 研究并实现 Hysteria2 + Reality 或可验证替代方案。（下一阶段）
7. 新增 Trojan。
8. 新增 Shadowsocks。
9. 新增 TUIC。
10. 完善 Clash 订阅。
11. 再考虑链式后端支持更多协议。

## 20. 与 fscarmen 脚本的关系

可以参考：

- 协议默认值。
- sing-box inbound/outbound 配置结构。
- 客户端链接生成格式。
- 防火墙端口保存思路。
- sing-box 下载和版本选择思路。

不建议移植：

- 整个菜单系统。
- 直接执行远程脚本。
- Argo/WARP/TCP 优化一键调用。
- 不可控的系统级全量卸载逻辑。
- 与 Nat xyz 数据库无关的订阅模板体系。

## 21. 结论

Nat xyz 可以融合 fscarmen/sing-box.sh 的多协议能力，但应采用“协议 handler + 通用节点参数 + 多协议配置生成 + 订阅转换”的产品化路线，而不是直接把一键脚本嵌入 WebUI。

第一阶段 Hysteria2 端到端闭环已经完成，并已验证 v2rayNG 与 NekoBox/sing-box 两类客户端。后续应在不破坏现有 VLESS Reality、Hysteria2 和链式代理的前提下，优先研究 Hysteria2 + Reality 或可验证替代方案，再复制同一架构扩展 Trojan、Shadowsocks、TUIC。这样风险最低，也最容易测试和回滚。
