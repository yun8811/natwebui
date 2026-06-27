from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import traceback
from threading import Lock
from typing import Any

from .db import (
    list_direct_vless_nodes_by_endpoint,
    mark_deployment_failed,
    mark_deployment_running,
    mark_deployment_success,
    update_node_generated_fields,
)
from .deployer import DeployError, run_multi_real_deploy, run_real_deploy

EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="nat-webui-deploy")
_RUNNING_DEPLOYS: set[str] = set()
_RUNNING_LOCK = Lock()


def is_deploy_running(deploy_id: str) -> bool:
    with _RUNNING_LOCK:
        return deploy_id in _RUNNING_DEPLOYS



def submit_reinstall_job(*, deploy_id: str, node: dict[str, Any]) -> None:
    with _RUNNING_LOCK:
        if deploy_id in _RUNNING_DEPLOYS:
            return
        _RUNNING_DEPLOYS.add(deploy_id)
    EXECUTOR.submit(_run_reinstall_job, deploy_id, node)



def _run_reinstall_job(deploy_id: str, node: dict[str, Any]) -> None:
    try:
        mark_deployment_running(deploy_id)
        try:
            if node.get("protocol_type") == "vless_reality_singbox":
                same_endpoint_nodes = [dict(item) for item in list_direct_vless_nodes_by_endpoint(str(node["ip"]), int(node["ssh_port"]))]
                result = run_multi_real_deploy(same_endpoint_nodes or [node])
            else:
                result = run_real_deploy(node)
        except DeployError as exc:
            mark_deployment_failed(
                deploy_id,
                failure_stage=exc.stage,
                summary_log=exc.message,
                raw_log=exc.raw_log,
            )
            return
        except Exception:
            mark_deployment_failed(
                deploy_id,
                failure_stage="unexpected_exception",
                summary_log="部署任务异常退出，请查看原始日志",
                raw_log=traceback.format_exc(),
            )
            return

        deployment_link = result.generated_vless_link
        if result.node_results:
            for node_result in result.node_results:
                if node_result.node_id == node["node_id"]:
                    deployment_link = node_result.generated_vless_link
                    break
        mark_deployment_success(
            deploy_id,
            summary_log=result.summary_log,
            raw_log=result.raw_log,
            generated_vless_link=deployment_link,
        )
        if result.node_results:
            for node_result in result.node_results:
                update_node_generated_fields(
                    node_result.node_id,
                    selected_reality_target=node_result.selected_reality_target,
                    generated_uuid=node_result.generated_uuid,
                    generated_private_key=node_result.generated_private_key,
                    generated_public_key=node_result.generated_public_key,
                    generated_short_id=node_result.generated_short_id,
                    last_vless_link=node_result.generated_vless_link,
                )
        else:
            update_node_generated_fields(
                node["node_id"],
                selected_reality_target=result.selected_reality_target,
                generated_uuid=result.generated_uuid,
                generated_private_key=result.generated_private_key,
                generated_public_key=result.generated_public_key,
                generated_short_id=result.generated_short_id,
                last_vless_link=result.generated_vless_link,
            )
    finally:
        with _RUNNING_LOCK:
            _RUNNING_DEPLOYS.discard(deploy_id)
