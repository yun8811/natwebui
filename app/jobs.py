from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

from .db import (
    mark_deployment_failed,
    mark_deployment_running,
    mark_deployment_success,
    update_node_generated_fields,
)
from .deployer import DeployError, run_real_deploy

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
            result = run_real_deploy(node)
        except DeployError as exc:
            mark_deployment_failed(
                deploy_id,
                failure_stage=exc.stage,
                summary_log=exc.message,
                raw_log=exc.raw_log,
            )
            return

        update_node_generated_fields(
            node["node_id"],
            selected_reality_target=result.selected_reality_target,
            generated_uuid=result.generated_uuid,
            generated_private_key=result.generated_private_key,
            generated_public_key=result.generated_public_key,
            generated_short_id=result.generated_short_id,
            last_vless_link=result.generated_vless_link,
        )
        mark_deployment_success(
            deploy_id,
            summary_log=result.summary_log,
            raw_log=result.raw_log,
            generated_vless_link=result.generated_vless_link,
        )
    finally:
        with _RUNNING_LOCK:
            _RUNNING_DEPLOYS.discard(deploy_id)
