from __future__ import annotations

import base64
import json
import os
import urllib.parse
import uuid

import pytest
import yaml
from fastapi.testclient import TestClient

os.environ.setdefault("NAT_WEBUI_DB_PATH", f"/tmp/nat_webui_test_{uuid.uuid4().hex}.db")

from app import jobs, main
from app.chain_deployer import build_front_chain_config
from app.deployer import DeployedNodeResult, DeployResult, build_agent_script, build_remote_script, build_singbox_config, build_tunnel_remote_script, build_vless_link, choose_reality_target, extract_pem_certificate, generate_reality_materials, resolve_host_for_ssh
from app.db import create_deployment_record, create_import_group, create_node_record, delete_import_group, get_deployment, get_node, init_db, list_chain_backend_nodes, list_direct_vless_nodes, list_import_groups, list_nodes, mark_deployment_failed, set_node_generated_fields
from app.main import app, build_clash_subscription_payload, build_subscription_payload, display_vless_link_for_node
from app.link_labels import replace_vless_fragment, vless_remark_for_node
from app.protocols.models import ProtocolBuildContext
from app.protocols.registry import get_protocol, list_protocols

init_db()


client = TestClient(app)


def test_protocol_registry_contains_vless_reality_handler() -> None:
    handler = get_protocol("vless_reality_singbox")
    assert handler is not None
    assert handler.display_name == "VLESS Reality"
    assert handler.supports_deploy is True
    assert handler.supports_subscription is True
    assert handler.supports_chain_backend is True
    assert get_protocol("vless_reality") is handler
    assert handler in list_protocols()


def test_build_singbox_config_uses_protocol_registry_for_vless_reality() -> None:
    node = {
        "node_id": "node_registry",
        "protocol_type": "vless_reality_singbox",
        "listen_port": 2443,
    }
    config = json.loads(
        build_singbox_config(
            node,
            generated_uuid="11111111-1111-1111-1111-111111111111",
            generated_private_key="private-key",
            generated_short_id="abcd1234",
            selected_reality_target="www.example.com",
        )
    )
    inbound = config["inbounds"][0]
    assert inbound["type"] == "vless"
    assert inbound["tag"] == "vless-reality-node_registry"
    assert inbound["listen_port"] == 2443
    assert inbound["users"] == [{"uuid": "11111111-1111-1111-1111-111111111111", "flow": "xtls-rprx-vision"}]
    assert inbound["tls"]["server_name"] == "www.example.com"
    assert inbound["tls"]["reality"]["short_id"] == ["abcd1234"]



def test_protocol_registry_contains_hysteria2_handler() -> None:
    handler = get_protocol("hysteria2")
    assert handler is not None
    assert handler.display_name == "Hysteria2"
    assert handler.supports_deploy is True
    assert handler.supports_subscription is True
    assert handler.supports_chain_backend is False
    assert get_protocol("hy2") is handler


def test_hysteria2_handler_builds_inbound_and_share_link() -> None:
    handler = get_protocol("hysteria2")
    node = {
        "node_id": "node_hy2",
        "name": "HY2_NODE",
        "protocol_type": "hysteria2",
        "ip": "node.example.com",
        "public_port": 2443,
        "listen_port": 2443,
        "hy2_up_mbps": 50,
        "hy2_down_mbps": 300,
    }
    context = ProtocolBuildContext(
        node=node,
        materials={
            "generated_uuid": "hy2-password",
            "selected_reality_target": "www.example.com",
            "certificate_public_key_sha256": "VlS7cOEt+f5NEknYt6n5PtVdu+B6eUrQh6Hz/pWJ3us=",
            "certificate_sha256": "b2c0a1d9a3d4e5f67890123456789abcdef0123456789abcdef0123456789ab",
            "remark": "HY2_NODE",
        },
    )
    inbound = handler.build_inbound(context)
    assert inbound["type"] == "hysteria2"
    assert inbound["tag"] == "hysteria2-node_hy2"
    assert inbound["listen_port"] == 2443
    assert inbound["users"] == [{"password": "hy2-password"}]
    assert inbound["up_mbps"] == 50
    assert inbound["down_mbps"] == 300
    assert inbound["ignore_client_bandwidth"] is False
    assert inbound["tls"]["alpn"] == ["h3"]
    assert inbound["tls"]["min_version"] == "1.3"
    assert inbound["tls"]["max_version"] == "1.3"
    assert inbound["tls"]["server_name"] == "www.example.com"
    assert inbound["tls"]["certificate_path"] == "/etc/sing-box/hysteria2-cert.pem"
    assert inbound["tls"]["key_path"] == "/etc/sing-box/hysteria2-key.pem"
    link = handler.build_share_link(context)
    assert link.startswith("hysteria2://hy2-password@node.example.com:2443?")
    assert "sni=www.example.com" in link
    assert "pinSHA256=5654bb70e12df9fe4d1249d8b7a9f93ed55dbbe07a794ad087a1f3fe9589deeb" in link
    assert "pinnedPeerCertSha256=b2c0a1d9a3d4e5f67890123456789abcdef0123456789abcdef0123456789ab" in link
    assert "verifyPeerCertByName=www.example.com" in link
    assert "insecure=1" in link
    assert "obfs=none" in link
    assert "upmbps=50" in link
    assert "downmbps=300" in link
    assert link.endswith("#HY2_NODE")


def test_build_singbox_config_uses_protocol_registry_for_hysteria2() -> None:
    config = json.loads(
        build_singbox_config(
            {"node_id": "node_hy2_config", "protocol_type": "hysteria2", "listen_port": 2444, "hy2_up_mbps": 80, "hy2_down_mbps": 400},
            generated_uuid="hy2-password",
            generated_private_key="",
            generated_short_id="",
            selected_reality_target="www.example.com",
        )
    )
    inbound = config["inbounds"][0]
    assert inbound["type"] == "hysteria2"
    assert inbound["tag"] == "hysteria2-node_hy2_config"
    assert inbound["users"] == [{"password": "hy2-password"}]
    assert inbound["up_mbps"] == 80
    assert inbound["down_mbps"] == 400
    assert inbound["ignore_client_bandwidth"] is False
    assert inbound["tls"]["alpn"] == ["h3"]
    assert inbound["tls"]["min_version"] == "1.3"
    assert inbound["tls"]["max_version"] == "1.3"



def test_protocol_registry_contains_anytls_handler() -> None:
    handler = get_protocol("anytls")
    assert handler is not None
    assert handler.display_name == "AnyTLS"
    assert handler.supports_deploy is True
    assert handler.supports_subscription is True
    assert handler.supports_chain_backend is False
    assert get_protocol("anytls_singbox") is handler


def test_anytls_handler_builds_inbound_and_share_link() -> None:
    handler = get_protocol("anytls")
    node = {
        "node_id": "node_anytls",
        "name": "ANYTLS_NODE",
        "protocol_type": "anytls",
        "ip": "node.example.com",
        "public_port": 2443,
        "listen_port": 2443,
        "selected_reality_target": "www.example.com",
    }
    context = ProtocolBuildContext(
        node=node,
        materials={
            "generated_uuid": "anytls-password",
            "certificate_public_key_sha256": "VlS7cOEt+f5NEknYt6n5PtVdu+B6eUrQh6Hz/pWJ3us=",
            "certificate_sha256": "b2:c0:a1:d9:a3:d4:e5:f6:78:90:12:34:56:78:9a:bc:de:f0:12:34:56:78:9a:bc:de:f0:12:34:56:78:9a:bc",
            "tls_certificate": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----",
        },
    )
    inbound = handler.build_inbound(context)
    assert inbound["type"] == "anytls"
    assert inbound["tag"] == "anytls-in-node_anytls"
    assert inbound["listen"] == "::"
    assert inbound["listen_port"] == 2443
    assert inbound["users"] == [{"password": "anytls-password"}]
    assert inbound["padding_scheme"] == []
    assert inbound["tls"]["server_name"] == "www.example.com"
    assert inbound["tls"]["certificate_path"] == "/etc/sing-box/anytls-cert.pem"
    assert inbound["tls"]["key_path"] == "/etc/sing-box/anytls-key.pem"

    link = handler.build_share_link(context)
    assert link.startswith("anytls://anytls-password@node.example.com:2443?")
    assert "sni=www.example.com" in link
    assert "insecure=1" in link
    assert "pinSHA256=VlS7cOEt%2Bf5NEknYt6n5PtVdu%2BB6eUrQh6Hz%2FpWJ3us%3D" in link
    assert "pinnedPeerCertSha256=VlS7cOEt%2Bf5NEknYt6n5PtVdu%2BB6eUrQh6Hz%2FpWJ3us%3D" in link
    assert "hpkp=b2%3Ac0%3Aa1%3Ad9%3Aa3%3Ad4%3Ae5%3Af6%3A78%3A90%3A12%3A34%3A56%3A78%3A9a%3Abc%3Ade%3Af0%3A12%3A34%3A56%3A78%3A9a%3Abc%3Ade%3Af0%3A12%3A34%3A56%3A78%3A9a%3Abc" in link
    assert "tls_certificate=" not in link
    assert "-----BEGIN" not in link
    assert link.endswith("#ANYTLS_NODE")


def test_build_singbox_config_uses_protocol_registry_for_anytls() -> None:
    config = json.loads(
        build_singbox_config(
            {"node_id": "node_anytls_config", "protocol_type": "anytls", "listen_port": 2444, "selected_reality_target": "www.example.com"},
            generated_uuid="anytls-password",
            generated_private_key="",
            generated_short_id="",
            selected_reality_target="www.example.com",
        )
    )
    inbound = config["inbounds"][0]
    assert inbound["type"] == "anytls"
    assert inbound["tag"] == "anytls-in-node_anytls_config"
    assert inbound["users"] == [{"password": "anytls-password"}]
    assert inbound["padding_scheme"] == []
    assert inbound["tls"]["server_name"] == "www.example.com"


def test_anytls_link_to_clash_subscription_payload() -> None:
    node_id = create_node_record(
        {
            "name": "ANYTLS_SUB",
            "ip": "node.example.com",
            "ssh_port": 2222,
            "ssh_user": "root",
            "ssh_password": "pass",
            "public_port": 2443,
            "listen_port": 2443,
            "protocol_type": "anytls",
            "selected_reality_target": "www.example.com",
            "last_vless_link": "anytls://passw0rd@node.example.com:2443?sni=www.example.com&fp=chrome&insecure=1&pinSHA256=VlS7cOEt%2Bf5NEknYt6n5PtVdu%2BB6eUrQh6Hz%2FpWJ3us%3D#ANYTLS_SUB",
        }
    )
    set_node_generated_fields(
        node_id,
        selected_reality_target="www.example.com",
        generated_uuid="passw0rd",
        generated_public_key="VlS7cOEt+f5NEknYt6n5PtVdu+B6eUrQh6Hz/pWJ3us=",
        generated_short_id="",
        last_vless_link="anytls://passw0rd@node.example.com:2443?sni=www.example.com&fp=chrome&insecure=1&pinSHA256=VlS7cOEt%2Bf5NEknYt6n5PtVdu%2BB6eUrQh6Hz%2FpWJ3us%3D#ANYTLS_SUB",
    )

    payload = build_subscription_payload("direct")
    decoded = base64.b64decode(payload).decode("utf-8")
    assert "anytls://passw0rd@node.example.com:2443" in decoded

    clash_payload = build_clash_subscription_payload("direct")
    clash = yaml.safe_load(clash_payload)
    proxy = next(item for item in clash["proxies"] if item["name"] == "ANYTLS_SUB")
    assert proxy["type"] == "anytls"
    assert proxy["server"] == "node.example.com"
    assert proxy["port"] == 2443
    assert proxy["password"] == "passw0rd"
    assert proxy["sni"] == "www.example.com"
    assert proxy["client-fingerprint"] == "chrome"
    assert proxy["skip-cert-verify"] is True
    assert proxy["certificate-public-key-sha256"] == "VlS7cOEt+f5NEknYt6n5PtVdu+B6eUrQh6Hz/pWJ3us="

def login() -> None:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "change-me-before-production"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_login_page() -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "管理员登录" in response.text


def test_login_success_redirects_to_nodes() -> None:
    response = client.post(
        "/login",
        data={"username": "admin", "password": "change-me-before-production"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/nodes"


def test_nodes_requires_login() -> None:
    fresh = TestClient(app)
    response = fresh.get("/nodes", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_import_groups_and_group_subscription() -> None:
    login()
    group_name = f"测试组-{uuid.uuid4().hex[:6]}"
    created = client.post("/import-groups", data={"name": group_name}, follow_redirects=False)
    assert created.status_code == 303
    group = next(group for group in list_import_groups() if group["name"] == group_name)
    group_id = group["group_id"]

    imported = client.post(
        "/nodes/import",
        data={
            "import_group_id": group_id,
            "links": "vless://11111111-1111-1111-1111-111111111111@example.com:443?type=tcp#grouped",
        },
        follow_redirects=False,
    )
    assert imported.status_code == 200
    node = next(node for node in list_nodes() if node["protocol_type"] == "imported_vless" and node["import_group_id"] == group_id)
    assert node["name"]

    nodes_page = client.get("/nodes")
    assert nodes_page.status_code == 200
    assert group_name in nodes_page.text
    payload = build_subscription_payload(f"import_group:{group_id}")
    grouped_payload = base64.b64decode(payload).decode()
    assert "example.com:443" in grouped_payload
    assert grouped_payload.count("vless://") == 1

    deleted = client.post(f"/import-groups/{group_id}/delete", follow_redirects=False)
    assert deleted.status_code == 303
    assert get_node(node["node_id"])["import_group_id"] is None
    assert delete_import_group(group_id) is False


def test_nodes_page_after_login() -> None:
    login()
    response = client.get("/nodes")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "节点列表" in response.text
    assert "新建节点" in response.text
    assert "直连节点" in response.text
    assert "链式节点" in response.text
    assert "复制直连 v2rayNG 订阅 URL" in response.text
    assert "复制直连 sing-box / NekoBox 订阅 URL" in response.text
    assert "复制链式 Clash 订阅 URL" in response.text
    assert "const STATUS_REFRESH_MS = 60 * 1000;" in response.text
    assert "window.location.reload()" in response.text



def test_nodes_page_uses_local_svg_flags_with_badge_fallback() -> None:
    login()
    create_node_record(
        {
            "name": f"FLAG_TEST_{uuid.uuid4().hex[:6]}",
            "ip": "198.51.100.88",
            "ssh_port": 2288,
            "ssh_user": "root",
            "ssh_password": "test-pass",
            "public_port": 443,
            "listen_port": 443,
            "protocol_type": "vless_reality_singbox",
            "manual_country_code": "US",
            "manual_region_label": "美国",
            "cf_host": "",
            "cf_tunnel_token": "",
            "ws_port": 8080,
            "ws_path": "/",
            "front_node_id": None,
            "backend_node_id": None,
            "chain_mode": None,
        }
    )
    response = client.get("/nodes")
    assert response.status_code == 200
    assert 'class="flag-icon"' in response.text
    assert 'src="/static/flags/' in response.text
    assert '.svg' in response.text
    assert 'class="flag-badge"' in response.text
    assert 'force-flag-badge' not in response.text


def test_failed_reinstall_preserves_existing_deployed_node_status() -> None:
    node_id = create_node_record(
        {
            "name": "LIVE_NODE_KEEP_STATUS",
            "ip": "198.51.100.91",
            "ssh_port": 2291,
            "ssh_user": "root",
            "ssh_password": "pass",
            "public_port": 443,
            "listen_port": 443,
        }
    )
    node = get_node(node_id)
    set_node_generated_fields(
        node_id,
        selected_reality_target=node["selected_reality_target"] or "www.example.com",
        generated_uuid=node["generated_uuid"] or "11111111-1111-1111-1111-111111111111",
        generated_public_key=node["generated_public_key"] or "test-public-key",
        generated_short_id=node["generated_short_id"] or "abcd1234",
        last_vless_link="vless://11111111-1111-1111-1111-111111111111@198.51.100.91:443?security=reality&type=tcp#LIVE_NODE_KEEP_STATUS",
    )
    deploy_id = create_deployment_record(node_id=node_id, action_type="reinstall")
    mark_deployment_failed(
        deploy_id,
        failure_stage="ssh_probe",
        summary_log="SSH 连接失败",
        raw_log="ssh: connect timed out",
    )
    node = get_node(node_id)
    deployment = get_deployment(deploy_id)
    assert deployment["result"] == "failed"
    assert node["status"] == "online"
    assert node["last_vless_link"].startswith("vless://11111111")


def test_first_deploy_failure_marks_never_deployed_node_failed() -> None:
    node_id = create_node_record(
        {
            "name": "NEW_NODE_FAIL_STATUS",
            "ip": "198.51.100.92",
            "ssh_port": 2292,
            "ssh_user": "root",
            "ssh_password": "pass",
            "public_port": 443,
            "listen_port": 443,
        }
    )
    deploy_id = create_deployment_record(node_id=node_id, action_type="reinstall")
    mark_deployment_failed(
        deploy_id,
        failure_stage="deploy",
        summary_log="部署失败",
        raw_log="ERROR",
    )
    node = get_node(node_id)
    deployment = get_deployment(deploy_id)
    assert deployment["result"] == "failed"
    assert node["status"] == "deploy_failed"

def test_create_reinstall_and_delete_node_flow(monkeypatch) -> None:
    login()

    unique_suffix = "35222"
    create_response = client.post(
        "/nodes/new",
        data={
            "name": "NAT_TEST",
            "ip": "198.51.100.20",
            "ssh_port": unique_suffix,
            "ssh_user": "root",
            "ssh_password": "test-pass",
            "public_port": "44321",
            "listen_port": "2443",
            "selected_reality_target": "www.example.com",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 303
    detail_url = create_response.headers["location"]
    assert detail_url.startswith("/nodes/node_")

    detail_response = client.get(detail_url)
    assert detail_response.status_code == 200
    assert "NAT_TEST" in detail_response.text
    assert "198.51.100.20" in detail_response.text

    node_id = detail_url.rsplit("/", 1)[-1]
    edit_response = client.post(
        f"/nodes/{node_id}/edit",
        data={
            "name": "NAT_TEST_EDITED",
            "ip": "198.51.100.20",
            "ssh_port": unique_suffix,
            "ssh_user": "root",
            "ssh_password": "test-pass-2",
            "public_port": "44322",
            "listen_port": "2444",
            "selected_reality_target": "www.example.com",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code == 303
    assert edit_response.headers["location"] == detail_url

    edited_detail = client.get(detail_url)
    assert "NAT_TEST_EDITED" in edited_detail.text
    node_after_edit = get_node(node_id)
    assert node_after_edit["selected_reality_target"] == "www.example.com"
    assert "44322" in edited_detail.text
    assert "2444" in edited_detail.text

    def fake_deploy_result(nodes):
        node = nodes[0] if isinstance(nodes, list) else nodes
        node_result = DeployedNodeResult(
            node_id=node["node_id"],
            generated_vless_link="vless://fake-uuid@198.51.100.20:44322?security=reality#NAT_TEST_EDITED",
            generated_uuid="fake-uuid",
            generated_private_key="fake-private",
            generated_public_key="fake-public",
            generated_short_id="fake-short-id",
            selected_reality_target="www.example.com",
        )
        return DeployResult(
            summary_log="真实部署已完成",
            raw_log="[stage] ssh_probe\nCONNECTED\n[stage] deploy\nOK: deploy finished",
            generated_vless_link=node_result.generated_vless_link,
            generated_uuid=node_result.generated_uuid,
            generated_private_key=node_result.generated_private_key,
            generated_public_key=node_result.generated_public_key,
            generated_short_id=node_result.generated_short_id,
            selected_reality_target=node_result.selected_reality_target,
            node_results=[node_result],
        )

    monkeypatch.setattr(jobs, "run_real_deploy", fake_deploy_result)
    monkeypatch.setattr(jobs, "run_multi_real_deploy", fake_deploy_result)

    submitted: list[tuple[str, dict]] = []

    def fake_submit(*, deploy_id: str, node: dict) -> None:
        submitted.append((deploy_id, node))
        jobs._run_reinstall_job(deploy_id, node)

    monkeypatch.setattr(main, "submit_reinstall_job", fake_submit)

    reinstall_response = client.post(f"/nodes/{node_id}/reinstall", follow_redirects=False)
    assert reinstall_response.status_code == 303
    deploy_url = reinstall_response.headers["location"]
    assert deploy_url.startswith("/deployments/deploy_")
    assert submitted

    deploy_detail = client.get(deploy_url)
    assert deploy_detail.status_code == 200
    assert "部署任务" in deploy_detail.text
    assert "success" in deploy_detail.text
    assert "OK: deploy finished" in deploy_detail.text

    api_response = client.get(deploy_url.replace("/deployments/", "/api/deployments/"))
    assert api_response.status_code == 200
    payload = api_response.json()
    assert payload["result"] == "success"
    assert payload["running"] is False

    after_reinstall = client.get(detail_url)
    assert "vless://fake-uuid@198.51.100.20:44322" in after_reinstall.text
    assert "title=\"复制链接\"" in after_reinstall.text

    delete_response = client.post(f"/nodes/{node_id}/delete", follow_redirects=False)
    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == "/nodes"

    missing = client.get(detail_url)
    assert missing.status_code == 404
    assert "节点不存在" in missing.text


def test_create_node_accepts_ddns_domain_as_ip_field_and_preserves_link_host() -> None:
    login()
    response = client.post(
        "/nodes/new",
        data={
            "name": "DDNS_DOMAIN_NODE",
            "ip": "https://Node.Example.COM/",
            "ssh_port": "2222",
            "ssh_user": "root",
            "ssh_password": "ddns-pass",
            "public_port": "20282",
            "listen_port": "20282",
            "protocol_type": "vless_reality_singbox",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    node_id = response.headers["location"].rsplit("/", 1)[-1]
    node = get_node(node_id)
    assert node["ip"] == "node.example.com"

    link = build_vless_link(
        dict(node),
        generated_uuid="11111111-1111-1111-1111-111111111111",
        generated_public_key="pubkey",
        generated_short_id="abcd",
        selected_reality_target="www.example.com",
    )
    assert "@node.example.com:20282" in link


def test_create_node_normalizes_custom_reality_target() -> None:
    login()
    response = client.post(
        "/nodes/new",
        data={
            "name": "CUSTOM_REALITY_NODE",
            "ip": "198.51.100.93",
            "ssh_port": "2393",
            "ssh_user": "root",
            "ssh_password": "custom-pass",
            "public_port": "44388",
            "listen_port": "44388",
            "protocol_type": "vless_reality_singbox",
            "selected_reality_target": "https://WWW.EXAMPLE.COM/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    node = get_node(response.headers["location"].rsplit("/", 1)[-1])
    assert node["selected_reality_target"] == "www.example.com"


def test_create_node_rejects_reality_target_with_port() -> None:
    login()
    response = client.post(
        "/nodes/new",
        data={
            "name": "BAD_REALITY_NODE",
            "ip": "198.51.100.89",
            "ssh_port": "2389",
            "ssh_user": "root",
            "ssh_password": "custom-pass",
            "public_port": "44389",
            "listen_port": "443",
            "protocol_type": "vless_reality_singbox",
            "selected_reality_target": "www.example.com:443",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Reality 伪装目标只填域名" in response.text

def test_build_agent_script_reads_public_base_url_at_runtime(monkeypatch) -> None:
    monkeypatch.delenv("NAT_WEBUI_PUBLIC_BASE_URL", raising=False)
    node = {"node_id": "node_agent", "name": "Agent", "ip": "node.example.com", "agent_token": "token"}
    with pytest.raises(Exception):
        build_agent_script(node)

    monkeypatch.setenv("NAT_WEBUI_PUBLIC_BASE_URL", "https://panel.example.com/")
    script = build_agent_script(node)
    assert "https://panel.example.com/agent/report" in script


def test_hysteria2_remote_script_checks_udp_listener() -> None:
    from app.deployer import build_remote_script

    node = {
        "node_id": "node_hy2_remote",
        "protocol_type": "hysteria2",
        "ip": "node.example.com",
        "listen_port": 2444,
        "agent_token": "agent-token",
    }
    script = build_remote_script(
        node,
        singbox_config='{"inbounds":[{"type":"hysteria2"}]}',
        node_meta='{}',
        agent_script='#!/bin/sh\n',
        singbox_archive_url="mirror.invalid/sing-box.tar.gz",
        singbox_archive_name="sing-box.tar.gz",
    )

    assert "ss_listen_args='-lunp'" in script
    assert "ss_check_args='-lun'" in script
    assert "ss -ltn | awk" not in script


def test_node_remote_scripts_fail_when_agent_cron_cannot_be_installed() -> None:
    common = {
        "node_id": "node_cron_guard",
        "ip": "node.example.com",
        "listen_port": 2444,
        "agent_token": "agent-token",
    }
    direct = build_remote_script(
        {**common, "protocol_type": "hysteria2"},
        singbox_config='{"inbounds":[{"type":"hysteria2"}]}',
        node_meta="{}",
        agent_script="#!/bin/sh\n",
        singbox_archive_url="mirror.invalid/sing-box.tar.gz",
        singbox_archive_name="sing-box.tar.gz",
    )
    tunnel = build_tunnel_remote_script(
        {**common, "protocol_type": "cf_vless_ws", "cf_tunnel_token": "token"},
        singbox_config="{}",
        node_meta="{}",
        agent_script="#!/bin/sh\n",
        singbox_assets={"amd64": {"url": "mirror.invalid/sing-box.tar.gz"}},
    )

    for script in (direct, tunnel):
        assert "ERROR: crontab is unavailable; cannot install Agent report schedule" in script
        assert "ERROR: failed to install Agent report schedule" in script
        assert "ERROR: Agent report schedule verification failed" in script
        assert "grep -Fqx '* * * * * /opt/natctl/agent/report.sh >> /opt/natctl/logs/agent.log 2>&1'" in script
        assert "|| true" not in script.split("ERROR: failed to install Agent report schedule", 1)[0].split("if ! command -v crontab", 1)[-1]
        assert script.rfind("echo 'OK: ") > script.rfind("Agent report schedule verification failed")


def test_extract_pem_certificate_ignores_ssh_warning() -> None:
    output = """-----BEGIN CERTIFICATE-----
MIIB
-----END CERTIFICATE-----
Warning: Permanently added '[node.example.com]:20009' (ED25519) to the list of known hosts.
"""

    assert extract_pem_certificate(output) == "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


def test_anytls_remote_script_checks_tcp_listener_and_generates_certificate() -> None:
    node = {
        "node_id": "node_anytls_remote",
        "protocol_type": "anytls",
        "ip": "node.example.com",
        "listen_port": 2444,
        "agent_token": "agent-token",
    }
    script = build_remote_script(
        node,
        singbox_config='{"inbounds":[{"type":"anytls","tls":{"server_name":"www.example.com","certificate_path":"/etc/sing-box/anytls-cert.pem","key_path":"/etc/sing-box/anytls-key.pem"}}]}',
        node_meta='{}',
        agent_script='#!/bin/sh\n',
        singbox_archive_url="mirror.invalid/sing-box.tar.gz",
        singbox_archive_name="sing-box.tar.gz",
    )

    assert "'hysteria2', 'anytls'" in script
    assert "anytls-cert.pem" in script
    assert "ss_listen_args='-ltnp'" in script
    assert "ss_check_args='-ltn'" in script


def test_remote_executor_error_includes_remote_output(monkeypatch) -> None:
    from app.deployer import RemoteCommandError, RemoteExecutor

    class Result:
        returncode = 1
        stdout = "[stage] before failure\n"
        stderr = "missing package\n"

    monkeypatch.setattr("app.deployer.resolve_host_for_ssh", lambda host: host)
    monkeypatch.setattr("app.deployer.subprocess.run", lambda *args, **kwargs: Result())

    executor = RemoteExecutor("node.example.com", 22, "root", "secret")
    try:
        executor.run("exit 1")
    except RemoteCommandError as exc:
        assert exc.returncode == 1
        assert "[stage] before failure" in str(exc)
        assert "missing package" in str(exc)
    else:
        raise AssertionError("RemoteCommandError not raised")

def test_deployer_uses_node_custom_reality_target() -> None:
    assert choose_reality_target({"selected_reality_target": "www.example.com"}) == "www.example.com"
    generated_uuid, generated_private_key, _generated_public_key, generated_short_id = generate_reality_materials()
    config_text = build_singbox_config(
        {"listen_port": 443, "selected_reality_target": "www.example.com"},
        generated_uuid=generated_uuid,
        generated_private_key=generated_private_key,
        generated_short_id=generated_short_id,
        selected_reality_target=choose_reality_target({"selected_reality_target": "www.example.com"}),
    )
    config = json.loads(config_text)
    tls = config["inbounds"][0]["tls"]
    assert tls["server_name"] == "www.example.com"
    assert tls["reality"]["handshake"]["server"] == "www.example.com"


def test_deployer_defaults_reality_target_when_blank() -> None:
    assert choose_reality_target({"selected_reality_target": ""}) == "www.example.com"


def test_vless_link_remark_uses_manual_country_flag() -> None:
    node = {
        "name": "demo-node",
        "ip": "node.example.com",
        "public_port": 20282,
        "manual_country_code": "TW",
        "manual_region_label": "",
        "country_code": "US",
    }
    link = build_vless_link(
        node,
        generated_uuid="11111111-1111-1111-1111-111111111111",
        generated_public_key="pubkey",
        generated_short_id="abcd",
        selected_reality_target="www.example.com",
    )
    assert urllib.parse.unquote(urllib.parse.urlparse(link).fragment) == "🇹🇼 demo-node"


def test_replace_vless_fragment_keeps_flag_when_node_name_changes() -> None:
    old_link = "vless://uuid@example.com:443?security=reality#old-name"
    node = {"name": "new-name", "manual_country_code": "JP", "manual_region_label": "", "country_code": ""}
    new_link = replace_vless_fragment(old_link, vless_remark_for_node(node))
    assert urllib.parse.unquote(urllib.parse.urlparse(new_link).fragment) == "🇯🇵 new-name"


def test_vless_remark_can_infer_country_from_node_name() -> None:
    node = {"name": "风见香港02", "manual_country_code": "", "manual_region_label": "", "country_code": ""}
    assert vless_remark_for_node(node) == "🇭🇰 风见香港02"


def test_chain_display_link_uses_backend_country_flag() -> None:
    front_id = create_node_record(
        {
            "name": "香港入口",
            "ip": "198.51.100.81",
            "ssh_port": 2281,
            "ssh_user": "root",
            "ssh_password": "front-pass",
            "public_port": 443,
            "listen_port": 443,
            "protocol_type": "vless_reality_singbox",
            "manual_country_code": "HK",
            "last_vless_link": "vless://11111111-1111-1111-1111-111111111111@198.51.100.81:443?security=reality&type=tcp#香港入口",
        }
    )
    backend_id = create_node_record(
        {
            "name": "美国落地",
            "ip": "198.51.100.82",
            "ssh_port": 2282,
            "ssh_user": "root",
            "ssh_password": "backend-pass",
            "public_port": 443,
            "listen_port": 443,
            "protocol_type": "vless_reality_singbox",
            "manual_country_code": "US",
            "last_vless_link": "vless://22222222-2222-2222-2222-222222222222@198.51.100.82:443?security=reality&type=tcp#美国落地",
        }
    )
    chain_id = create_node_record(
        {
            "name": "香港拉美国",
            "ip": "198.51.100.81",
            "ssh_port": 2281,
            "ssh_user": "root",
            "ssh_password": "front-pass",
            "public_port": 443,
            "listen_port": 443,
            "protocol_type": "vless_chain",
            "front_node_id": front_id,
            "backend_node_id": backend_id,
            "last_vless_link": "vless://33333333-3333-3333-3333-333333333333@198.51.100.81:443?security=reality&type=tcp#香港拉美国",
        }
    )
    nodes = {node["node_id"]: node for node in list_nodes()}
    decoded = urllib.parse.unquote(display_vless_link_for_node(nodes[chain_id], nodes))
    assert "#🇺🇸 香港拉美国" in decoded
    assert "#🇭🇰 香港拉美国" not in decoded


def test_vless_remark_falls_back_to_auto_country_code() -> None:
    node = {"name": "auto-node", "manual_country_code": "", "manual_region_label": "", "country_code": "US"}
    assert vless_remark_for_node(node) == "🇺🇸 auto-node"


def test_vless_remark_without_country_stays_name_only() -> None:
    node = {"name": "plain-node", "manual_country_code": "", "manual_region_label": "", "country_code": ""}
    assert vless_remark_for_node(node) == "plain-node"


def test_resolve_host_for_ssh_resolves_domain_but_keeps_ip_literal(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.deployer.socket.getaddrinfo",
        lambda host, *args, **kwargs: [(None, None, None, None, ("203.0.113.77", 0))],
    )
    assert resolve_host_for_ssh("example.com") == "203.0.113.77"
    assert resolve_host_for_ssh("198.51.100.5") == "198.51.100.5"



def test_create_node_allows_same_ssh_endpoint_but_rejects_port_conflict() -> None:
    login()
    first = client.post(
        "/nodes/new",
        data={
            "name": "NAT_DUP_FIRST",
            "ip": "203.0.113.10",
            "ssh_port": "22",
            "ssh_user": "root",
            "ssh_password": "dup-pass",
            "public_port": "44443",
            "listen_port": "44443",
        },
        follow_redirects=False,
    )
    assert first.status_code == 303

    allowed = client.post(
        "/nodes/new",
        data={
            "name": "NAT_DUP_SECOND_ALLOWED",
            "ip": "203.0.113.10",
            "ssh_port": "22",
            "ssh_user": "root",
            "ssh_password": "dup-pass",
            "public_port": "44444",
            "listen_port": "44444",
        },
        follow_redirects=False,
    )
    assert allowed.status_code == 303

    response = client.post(
        "/nodes/new",
        data={
            "name": "NAT_DUP_PORT_CONFLICT",
            "ip": "203.0.113.10",
            "ssh_port": "22",
            "ssh_user": "root",
            "ssh_password": "dup-pass",
            "public_port": "44443",
            "listen_port": "44445",
        },
    )
    assert response.status_code == 200
    assert "已存在相同 IP + 公网端口或监听端口 的节点记录" in response.text


def test_create_chain_node_record_preserves_front_and_backend_references() -> None:
    front_id = create_node_record(
        {
            "name": "FRONT_FOR_CHAIN",
            "ip": "198.51.100.31",
            "ssh_port": 2231,
            "ssh_user": "root",
            "ssh_password": "front-pass",
            "public_port": 443,
            "listen_port": 443,
        }
    )
    backend_id = create_node_record(
        {
            "name": "BACKEND_FOR_CHAIN",
            "ip": "198.51.100.32",
            "ssh_port": 2232,
            "ssh_user": "root",
            "ssh_password": "backend-pass",
            "public_port": 443,
            "listen_port": 443,
        }
    )
    chain_id = create_node_record(
        {
            "name": "CHAIN_FRONT_TO_BACKEND",
            "ip": "198.51.100.31",
            "ssh_port": 2231,
            "ssh_user": "root",
            "ssh_password": "front-pass",
            "protocol_type": "vless_chain",
            "front_node_id": front_id,
            "backend_node_id": backend_id,
            "chain_mode": "vless_reality_to_vless_reality",
            "public_port": 443,
            "listen_port": 443,
        }
    )

    chain = get_node(chain_id)
    assert chain is not None
    assert chain["protocol_type"] == "vless_chain"
    assert chain["front_node_id"] == front_id
    assert chain["backend_node_id"] == backend_id
    assert chain["chain_mode"] == "vless_reality_to_vless_reality"
    assert chain["front_node_name"] == "FRONT_FOR_CHAIN"
    assert chain["backend_node_name"] == "BACKEND_FOR_CHAIN"

    listed = {node["node_id"]: node for node in list_nodes()}
    assert listed[chain_id]["front_node_name"] == "FRONT_FOR_CHAIN"
    assert listed[chain_id]["backend_node_name"] == "BACKEND_FOR_CHAIN"


def test_inline_rename_only_updates_node_name() -> None:
    login()
    node_id = create_node_record(
        {
            "name": "INLINE_OLD_NAME",
            "ip": "198.51.100.71",
            "ssh_port": 2271,
            "ssh_user": "root",
            "ssh_password": "keep-pass",
            "public_port": 443,
            "listen_port": 443,
            "protocol_type": "vless_reality_singbox",
            "manual_country_code": "US",
            "last_vless_link": "vless://11111111-1111-1111-1111-111111111111@198.51.100.71:443?security=reality&type=tcp#INLINE_OLD_NAME",
        }
    )
    before = dict(get_node(node_id))
    response = client.post(
        f"/nodes/{node_id}/rename",
        data={"name": "INLINE_NEW_NAME"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/nodes"
    after = dict(get_node(node_id))
    assert after["name"] == "INLINE_NEW_NAME"
    for field in ["ip", "ssh_port", "ssh_user", "ssh_password", "protocol_type", "public_port", "listen_port", "manual_country_code", "last_vless_link"]:
        assert after[field] == before[field]

    empty_response = client.post(
        f"/nodes/{node_id}/rename",
        data={"name": "   "},
        follow_redirects=False,
    )
    assert empty_response.status_code == 303
    assert dict(get_node(node_id))["name"] == "INLINE_NEW_NAME"



def test_renamed_node_updates_export_and_subscription_link_name() -> None:
    login()
    node_id = create_node_record(
        {
            "name": "OLD_LINK_NAME",
            "ip": "198.51.100.61",
            "ssh_port": 2261,
            "ssh_user": "root",
            "ssh_password": "pass",
            "public_port": 443,
            "listen_port": 443,
        }
    )
    from app.db import get_conn
    with get_conn() as conn:
        conn.execute(
            "UPDATE nodes SET last_vless_link = ?, generated_uuid = ?, generated_public_key = ?, generated_short_id = ? WHERE node_id = ?",
            (
                "vless://11111111-1111-1111-1111-111111111111@198.51.100.61:443?security=reality&sni=www.example.com&pbk=pubkey&sid=abcd&type=tcp&flow=xtls-rprx-vision#OLD_LINK_NAME",
                "11111111-1111-1111-1111-111111111111",
                "pubkey",
                "abcd",
                node_id,
            ),
        )

    response = client.post(
        f"/nodes/{node_id}/edit",
        data={
            "name": "NEW_LINK_NAME",
            "ip": "198.51.100.61",
            "ssh_port": "2261",
            "ssh_user": "root",
            "ssh_password": "pass",
            "public_port": "443",
            "listen_port": "443",
            "protocol_type": "vless_reality_singbox",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    detail_response = client.get(f"/nodes/{node_id}")
    assert detail_response.status_code == 200
    assert "NEW_LINK_NAME" in detail_response.text
    assert "OLD_LINK_NAME" not in detail_response.text

    subscription_response = client.get("/nodes")
    assert subscription_response.status_code == 200
    token = subscription_response.text.split("/sub/")[1].split('"')[0]
    feed = client.get(f"/sub/{token}")
    assert feed.status_code == 200
    import base64
    decoded = base64.b64decode(feed.text).decode("utf-8")
    assert "NEW_LINK_NAME" in decoded
    assert "OLD_LINK_NAME" not in decoded



def test_scoped_subscription_feeds_split_direct_and_chain_nodes() -> None:
    import base64

    direct_id = create_node_record(
        {
            "name": "DIRECT_SUB_NODE",
            "ip": "198.51.100.71",
            "ssh_port": 2271,
            "ssh_user": "root",
            "ssh_password": "pass",
            "public_port": 443,
            "listen_port": 443,
        }
    )
    chain_id = create_node_record(
        {
            "name": "CHAIN_SUB_NODE",
            "ip": "198.51.100.72",
            "ssh_port": 2272,
            "ssh_user": "root",
            "ssh_password": "pass",
            "protocol_type": "vless_chain",
            "public_port": 443,
            "listen_port": 443,
        }
    )
    from app.db import get_conn
    with get_conn() as conn:
        conn.execute(
            "UPDATE nodes SET last_vless_link = ?, generated_uuid = ?, generated_public_key = ?, generated_short_id = ? WHERE node_id = ?",
            (
                "vless://22222222-2222-2222-2222-222222222222@198.51.100.71:443?security=reality&sni=www.example.com&pbk=directpub&sid=abcd&type=tcp&flow=xtls-rprx-vision#DIRECT_SUB_NODE",
                "22222222-2222-2222-2222-222222222222",
                "directpub",
                "abcd",
                direct_id,
            ),
        )
        conn.execute(
            "UPDATE nodes SET last_vless_link = ?, generated_uuid = ?, generated_public_key = ?, generated_short_id = ? WHERE node_id = ?",
            (
                "vless://33333333-3333-3333-3333-333333333333@198.51.100.72:443?security=reality&sni=www.example.com&pbk=chainpub&sid=efgh&type=tcp&flow=xtls-rprx-vision#CHAIN_SUB_NODE",
                "33333333-3333-3333-3333-333333333333",
                "chainpub",
                "efgh",
                chain_id,
            ),
        )

    login()
    page = client.get("/nodes")
    assert page.status_code == 200
    assert "scope=direct" in page.text
    assert "scope=chain" in page.text
    token = page.text.split("/sub/")[1].split('?')[0]

    direct_feed = client.get(f"/sub/{token}?scope=direct")
    assert direct_feed.status_code == 200
    direct_decoded = base64.b64decode(direct_feed.text).decode("utf-8")
    assert "22222222-2222-2222-2222-222222222222" in direct_decoded
    assert "33333333-3333-3333-3333-333333333333" not in direct_decoded

    chain_feed = client.get(f"/sub/{token}?scope=chain")
    assert chain_feed.status_code == 200
    chain_decoded = base64.b64decode(chain_feed.text).decode("utf-8")
    assert "33333333-3333-3333-3333-333333333333" in chain_decoded
    assert "22222222-2222-2222-2222-222222222222" not in chain_decoded

    all_feed = client.get(f"/sub/{token}")
    assert all_feed.status_code == 200
    all_decoded = base64.b64decode(all_feed.text).decode("utf-8")
    assert "22222222-2222-2222-2222-222222222222" in all_decoded
    assert "33333333-3333-3333-3333-333333333333" in all_decoded

    direct_clash = client.get(f"/sub/{token}/clash?scope=direct")
    assert direct_clash.status_code == 200
    assert "DIRECT_SUB_NODE" in direct_clash.text
    assert "CHAIN_SUB_NODE" not in direct_clash.text

    chain_clash = client.get(f"/sub/{token}/clash?scope=chain")
    assert chain_clash.status_code == 200
    assert "CHAIN_SUB_NODE" in chain_clash.text
    assert "DIRECT_SUB_NODE" not in chain_clash.text

def test_edit_chain_node_name_redirects_to_detail_and_updates() -> None:
    login()
    front_id = create_node_record(
        {
            "name": "FRONT_EDIT_CHAIN",
            "ip": "198.51.100.41",
            "ssh_port": 2241,
            "ssh_user": "root",
            "ssh_password": "front-pass",
            "public_port": 443,
            "listen_port": 443,
        }
    )
    backend_id = create_node_record(
        {
            "name": "BACKEND_EDIT_CHAIN",
            "ip": "198.51.100.42",
            "ssh_port": 2242,
            "ssh_user": "root",
            "ssh_password": "backend-pass",
            "public_port": 443,
            "listen_port": 443,
        }
    )
    chain_id = create_node_record(
        {
            "name": "CHAIN_OLD_NAME",
            "ip": "198.51.100.41",
            "ssh_port": 2241,
            "ssh_user": "root",
            "ssh_password": "front-pass",
            "protocol_type": "vless_chain",
            "front_node_id": front_id,
            "backend_node_id": backend_id,
            "chain_mode": "vless_reality_to_vless_reality",
            "public_port": 443,
            "listen_port": 443,
        }
    )

    response = client.post(
        f"/nodes/{chain_id}/edit",
        data={
            "name": "CHAIN_NEW_NAME",
            "protocol_type": "vless_chain",
            "front_node_id": front_id,
            "backend_node_id": backend_id,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/nodes/{chain_id}"
    assert get_node(chain_id)["name"] == "CHAIN_NEW_NAME"

    detail_response = client.get(f"/nodes/{chain_id}")
    assert detail_response.status_code == 200
    assert "CHAIN_NEW_NAME" in detail_response.text


def test_build_front_chain_config_rejects_tunnel_ws_backend() -> None:
    config = {
        "inbounds": [
            {
                "type": "vless",
                "tag": "in-1",
                "tls": {"reality": {"enabled": True}},
                "users": [{"name": "old", "uuid": "old-uuid"}],
            }
        ],
        "outbounds": [
            {"tag": "direct", "type": "direct"},
            {"tag": "old-out", "type": "vless", "server": "old", "server_port": 1234},
        ],
        "route": {"rules": [{"outbound": "old-out"}]},
    }
    backend = {
        "protocol_type": "cf_vless_ws",
        "cf_host": "backend.example.com",
        "ws_path": "/",
        "generated_uuid": "33333333-3333-3333-3333-333333333333",
    }

    with pytest.raises(Exception, match="tunnel backend is disabled"):
        build_front_chain_config(config, chain_tag="chain-x", chain_uuid="chain-uuid", backend=backend)


def test_build_front_chain_config_uses_reality_backend_when_not_tunnel() -> None:
    config = {
        "inbounds": [
            {"type": "vless", "tag": "in-1", "tls": {"reality": {"enabled": True}}, "users": []}
        ],
        "outbounds": [],
        "route": {"rules": []},
    }
    backend = {
        "protocol_type": "vless_reality_singbox",
        "ip": "198.51.100.91",
        "public_port": 443,
        "generated_uuid": "44444444-4444-4444-4444-444444444444",
        "generated_public_key": "pub-key",
        "generated_short_id": "short-id",
        "selected_reality_target": "www.example.com",
    }

    updated = build_front_chain_config(config, chain_tag="chain-y", chain_uuid="chain-uuid", backend=backend)
    out = next(item for item in updated["outbounds"] if item["tag"] == "chain-y-out")
    assert out["server"] == "198.51.100.91"
    assert out["server_port"] == 443
    assert out["tls"]["reality"]["public_key"] == "pub-key"
    assert out["tls"]["reality"]["short_id"] == "short-id"

def test_single_node_remote_script_cleans_stale_managed_port() -> None:
    script = build_remote_script(
        {
            "name": "CLEANUP_NODE",
            "ip": "198.51.100.90",
            "listen_port": 44300,
            "public_port": 44300,
            "generated_uuid": "11111111-1111-1111-1111-111111111111",
            "generated_private_key": "private-key",
            "generated_short_id": "abcd1234",
            "selected_reality_target": "www.example.com",
        },
        singbox_config="{}",
        node_meta="{}",
        agent_script="#!/bin/sh\necho ok\n",
        singbox_archive_url="https://example.com/sing-box.tar.gz",
        singbox_archive_name="sing-box.tar.gz",
    )

    assert "mkdir -p" in script
    assert "/etc/systemd/system" in script
    assert "command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]" in script
    assert "systemctl stop sing-box" in script
    assert "rc-service sing-box stop" in script
    assert "stale NAT WebUI sing-box process" in script
    assert "port 44300 is occupied by non-NAT-WebUI process" in script
    assert "ERROR: sing-box listen port is still occupied after cleanup" in script


def test_chain_form_excludes_tunnel_as_backend() -> None:
    login()
    front_id = create_node_record(
        {
            "name": "FRONT_FORM_REALITY",
            "ip": "198.51.100.71",
            "ssh_port": 2271,
            "ssh_user": "root",
            "ssh_password": "front-pass",
            "public_port": 443,
            "listen_port": 443,
            "protocol_type": "vless_reality_singbox",
            "last_vless_link": "vless://11111111-1111-1111-1111-111111111111@198.51.100.71:443?security=reality&type=tcp#FRONT_FORM_REALITY",
        }
    )
    tunnel_id = create_node_record(
        {
            "name": "BACKEND_FORM_TUNNEL",
            "ip": "198.51.100.72",
            "ssh_port": 2272,
            "ssh_user": "root",
            "ssh_password": "tunnel-pass",
            "protocol_type": "cf_vless_ws",
            "public_port": 443,
            "listen_port": 8080,
            "cf_host": "backend.example.com",
            "ws_port": 8080,
            "ws_path": "/",
            "generated_uuid": "22222222-2222-2222-2222-222222222222",
            "last_vless_link": "vless://22222222-2222-2222-2222-222222222222@backend.example.com:443?security=tls&type=ws#BACKEND_FORM_TUNNEL",
        }
    )

    direct_ids = {row["node_id"] for row in list_direct_vless_nodes()}
    backend_ids = {row["node_id"] for row in list_chain_backend_nodes()}
    assert front_id in direct_ids
    assert tunnel_id not in direct_ids
    assert front_id in backend_ids
    assert tunnel_id not in backend_ids

    imported_id = create_node_record(
        {
            "name": "IMPORTED_BACKEND_FORM",
            "protocol_type": "imported_vless",
            "ip": "203.0.113.88",
            "ssh_port": 22,
            "ssh_user": "imported",
            "ssh_password": "",
            "public_port": 443,
            "listen_port": 443,
            "last_vless_link": "vless://33333333-3333-3333-3333-333333333333@203.0.113.88:443?security=reality&type=tcp&sni=www.example.com&fp=chrome&pbk=pub-key&sid=short-id&flow=xtls-rprx-vision#IMPORTED_BACKEND_FORM",
        }
    )
    direct_ids = {row["node_id"] for row in list_direct_vless_nodes()}
    backend_ids = {row["node_id"] for row in list_chain_backend_nodes()}
    assert imported_id not in direct_ids
    assert imported_id in backend_ids

    response = client.get("/nodes/new-chain")
    assert response.status_code == 200
    html = response.text
    front_block = html.split('name="front_node_id"', 1)[1].split('name="backend_node_id"', 1)[0]
    backend_block = html.split('name="backend_node_id"', 1)[1].split('name="chain_mode"', 1)[0]
    assert "FRONT_FORM_REALITY · Reality · 198.51.100.71:443" in front_block
    assert "IMPORTED_BACKEND_FORM" not in front_block
    assert "BACKEND_FORM_TUNNEL" not in front_block
    assert "FRONT_FORM_REALITY · Reality · 198.51.100.71:443" in backend_block
    assert "IMPORTED_BACKEND_FORM" in backend_block
    assert "BACKEND_FORM_TUNNEL · tunnel · backend.example.com:443" not in backend_block


def test_build_front_chain_config_uses_imported_reality_backend() -> None:
    config = {
        "inbounds": [
            {"type": "vless", "tag": "in-1", "tls": {"reality": {"enabled": True}}, "users": []}
        ],
        "outbounds": [],
        "route": {"rules": []},
    }
    backend = {
        "protocol_type": "imported_vless",
        "last_vless_link": "vless://55555555-5555-5555-5555-555555555555@203.0.113.55:2443?security=reality&type=tcp&sni=www.example.com&fp=firefox&pbk=import-pub&sid=import-sid&flow=xtls-rprx-vision#Imported",
        "public_port": 2443,
    }

    updated = build_front_chain_config(config, chain_tag="chain-import", chain_uuid="chain-uuid", backend=backend)
    out = next(item for item in updated["outbounds"] if item["tag"] == "chain-import-out")
    assert out["server"] == "203.0.113.55"
    assert out["server_port"] == 2443
    assert out["uuid"] == "55555555-5555-5555-5555-555555555555"
    assert out["flow"] == "xtls-rprx-vision"
    assert out["tls"]["server_name"] == "www.example.com"
    assert out["tls"]["utls"]["fingerprint"] == "firefox"
    assert out["tls"]["reality"]["public_key"] == "import-pub"
    assert out["tls"]["reality"]["short_id"] == "import-sid"
    rule = updated["route"]["rules"][0]
    assert rule["auth_user"] == ["chain-import"]
    assert "user" not in rule

def test_phase2_markdown_exists() -> None:
    with open("PHASE2.md", "r", encoding="utf-8") as f:
        content = f.read()
    assert "Phase 2 Development Constraints" in content
    assert "VLESS + Reality -> VLESS + Reality" in content


def test_create_node_form_renders_hysteria2_protocol_value() -> None:
    login()
    response = client.get("/nodes/new")
    assert response.status_code == 200
    assert 'value="hysteria2"' in response.text

def test_create_hysteria2_node_and_subscription_payload() -> None:
    login()
    response = client.post(
        "/nodes/new",
        data={
            "name": "HY2_CREATE_NODE",
            "ip": "node.example.com",
            "ssh_port": "2299",
            "ssh_user": "root",
            "ssh_password": "hy2-pass",
            "public_port": "24443",
            "listen_port": "24443",
            "protocol_type": "hysteria2",
            "selected_reality_target": "www.example.com",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    node = get_node(response.headers["location"].rsplit("/", 1)[-1])
    assert node["protocol_type"] == "hysteria2"
    assert node["selected_reality_target"] == "www.example.com"

    from app.db import get_conn
    with get_conn() as conn:
        conn.execute(
            "UPDATE nodes SET last_vless_link = ?, generated_uuid = ? WHERE node_id = ?",
            ("hysteria2://hy2-password@node.example.com:24443?sni=www.example.com&pinSHA256=5654bb70e12df9fe4d1249d8b7a9f93ed55dbbe07a794ad087a1f3fe9589deeb&pinnedPeerCertSha256=b2c0a1d9a3d4e5f67890123456789abcdef0123456789abcdef0123456789ab&verifyPeerCertByName=www.example.com&insecure=1&obfs=none&upmbps=200&downmbps=1000#HY2_CREATE_NODE", "hy2-password", node["node_id"]),
        )

    payload = build_subscription_payload("direct")
    decoded = base64.b64decode(payload).decode("utf-8")
    assert "hysteria2://hy2-password@node.example.com:24443" in decoded

    xray_payload = build_subscription_payload("direct", client="xray")
    xray_decoded = base64.b64decode(xray_payload).decode("utf-8")
    hysteria2_line = next(line for line in xray_decoded.splitlines() if "HY2_CREATE_NODE" in line)
    assert "pinSHA256=b2c0a1d9a3d4e5f67890123456789abcdef0123456789abcdef0123456789ab" in hysteria2_line
    assert "insecure=1" not in hysteria2_line
    assert "pinnedPeerCertSha256=" not in hysteria2_line
    assert "verifyPeerCertByName=" not in hysteria2_line

    clash_payload = build_clash_subscription_payload("direct")
    assert "type: hysteria2" in clash_payload
    assert "skip-cert-verify: true" in clash_payload
    assert "certificate-public-key-sha256: VlS7cOEt+f5NEknYt6n5PtVdu+B6eUrQh6Hz/pWJ3us=" in clash_payload
    assert "certificate-public-key-sha256: ssCh2aPU5fZ4kBI0VniavN7wEjRWeJq83vASNFZ4mrA=" not in clash_payload
    assert "up: 200 Mbps" in clash_payload
    assert "down: 1000 Mbps" in clash_payload
