from __future__ import annotations

import os
import urllib.parse
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("NAT_WEBUI_DB_PATH", f"/tmp/nat_webui_test_{uuid.uuid4().hex}.db")

from app import jobs, main
from app.chain_deployer import build_front_chain_config
from app.deployer import build_vless_link, resolve_host_for_ssh
from app.db import create_deployment_record, create_node_record, get_deployment, get_node, init_db, list_chain_backend_nodes, list_direct_vless_nodes, list_nodes, mark_deployment_failed, update_node_generated_fields
from app.main import app, build_subscription_payload, display_vless_link_for_node
from app.link_labels import replace_vless_fragment, vless_remark_for_node

init_db()


client = TestClient(app)


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


def test_nodes_page_after_login() -> None:
    login()
    response = client.get("/nodes")
    assert response.status_code == 200
    assert "节点列表" in response.text
    assert "新建节点" in response.text
    assert "直连节点" in response.text
    assert "链式节点" in response.text
    assert "复制直连 v2rayN 订阅 URL" in response.text
    assert "复制链式 Clash 订阅 URL" in response.text



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
        selected_reality_target=node["selected_reality_target"] or "www.microsoft.com",
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
        },
        follow_redirects=False,
    )
    assert edit_response.status_code == 303
    assert edit_response.headers["location"] == detail_url

    edited_detail = client.get(detail_url)
    assert "NAT_TEST_EDITED" in edited_detail.text
    assert "44322" in edited_detail.text
    assert "2444" in edited_detail.text

    class FakeDeployResult:
        summary_log = "真实部署已完成"
        raw_log = "[stage] ssh_probe\nCONNECTED\n[stage] deploy\nOK: deploy finished"
        generated_vless_link = "vless://fake-uuid@198.51.100.20:44322?security=reality#NAT_TEST_EDITED"
        generated_uuid = "fake-uuid"
        generated_private_key = "fake-private"
        generated_public_key = "fake-public"
        generated_short_id = "fake-short-id"
        selected_reality_target = "www.microsoft.com"

    monkeypatch.setattr(jobs, "run_real_deploy", lambda node: FakeDeployResult())

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
            "ip": "https://HINET.Example.COM/",
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
    assert node["ip"] == "hinet.example.com"

    link = build_vless_link(
        dict(node),
        generated_uuid="11111111-1111-1111-1111-111111111111",
        generated_public_key="pubkey",
        generated_short_id="abcd",
        selected_reality_target="www.microsoft.com",
    )
    assert "@hinet.example.com:20282" in link


def test_vless_link_remark_uses_manual_country_flag() -> None:
    node = {
        "name": "hinet-lazy",
        "ip": "hinet.example.com",
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
        selected_reality_target="www.microsoft.com",
    )
    assert urllib.parse.unquote(urllib.parse.urlparse(link).fragment) == "🇹🇼 hinet-lazy"


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



def test_create_node_rejects_duplicate_ip_and_ssh_port() -> None:
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

    response = client.post(
        "/nodes/new",
        data={
            "name": "NAT_DUP_SECOND",
            "ip": "203.0.113.10",
            "ssh_port": "22",
            "ssh_user": "root",
            "ssh_password": "dup-pass",
            "public_port": "44443",
            "listen_port": "44443",
        },
    )
    assert response.status_code == 200
    assert "已存在相同 IP + SSH 端口 的节点记录" in response.text


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
                "vless://11111111-1111-1111-1111-111111111111@198.51.100.61:443?security=reality&sni=www.microsoft.com&pbk=pubkey&sid=abcd&type=tcp&flow=xtls-rprx-vision#OLD_LINK_NAME",
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
                "vless://22222222-2222-2222-2222-222222222222@198.51.100.71:443?security=reality&sni=www.microsoft.com&pbk=directpub&sid=abcd&type=tcp&flow=xtls-rprx-vision#DIRECT_SUB_NODE",
                "22222222-2222-2222-2222-222222222222",
                "directpub",
                "abcd",
                direct_id,
            ),
        )
        conn.execute(
            "UPDATE nodes SET last_vless_link = ?, generated_uuid = ?, generated_public_key = ?, generated_short_id = ? WHERE node_id = ?",
            (
                "vless://33333333-3333-3333-3333-333333333333@198.51.100.72:443?security=reality&sni=www.microsoft.com&pbk=chainpub&sid=efgh&type=tcp&flow=xtls-rprx-vision#CHAIN_SUB_NODE",
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
        "cf_host": "backend-tunnel.example.com",
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
        "selected_reality_target": "www.microsoft.com",
    }

    updated = build_front_chain_config(config, chain_tag="chain-y", chain_uuid="chain-uuid", backend=backend)
    out = next(item for item in updated["outbounds"] if item["tag"] == "chain-y-out")
    assert out["server"] == "198.51.100.91"
    assert out["server_port"] == 443
    assert out["tls"]["reality"]["public_key"] == "pub-key"
    assert out["tls"]["reality"]["short_id"] == "short-id"

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
            "cf_host": "backend-tunnel.example.com",
            "ws_port": 8080,
            "ws_path": "/",
            "generated_uuid": "22222222-2222-2222-2222-222222222222",
            "last_vless_link": "vless://22222222-2222-2222-2222-222222222222@backend-tunnel.example.com:443?security=tls&type=ws#BACKEND_FORM_TUNNEL",
        }
    )

    direct_ids = {row["node_id"] for row in list_direct_vless_nodes()}
    backend_ids = {row["node_id"] for row in list_chain_backend_nodes()}
    assert front_id in direct_ids
    assert tunnel_id not in direct_ids
    assert front_id in backend_ids
    assert tunnel_id not in backend_ids

    response = client.get("/nodes/new-chain")
    assert response.status_code == 200
    html = response.text
    front_block = html.split('name="front_node_id"', 1)[1].split('name="backend_node_id"', 1)[0]
    backend_block = html.split('name="backend_node_id"', 1)[1].split('name="chain_mode"', 1)[0]
    assert "FRONT_FORM_REALITY · Reality · 198.51.100.71:443" in front_block
    assert "BACKEND_FORM_TUNNEL" not in front_block
    assert "FRONT_FORM_REALITY · Reality · 198.51.100.71:443" in backend_block
    assert "BACKEND_FORM_TUNNEL · tunnel · backend-tunnel.example.com:443" not in backend_block

def test_phase2_markdown_exists() -> None:
    with open("PHASE2.md", "r", encoding="utf-8") as f:
        content = f.read()
    assert "Phase 2 Development Constraints" in content
    assert "VLESS + Reality -> VLESS + Reality" in content
