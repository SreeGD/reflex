"""Mock ActionsProvider — logs actions and simulates success."""

from __future__ import annotations

from typing import Optional

import random
from datetime import datetime, timezone


class MockActionsProvider:
    """Fulfills ActionsProvider protocol. Logs actions, simulates success.

    Tracks all executed actions so the demo can display what happened.
    """

    def __init__(self) -> None:
        self.executed_actions: list[dict] = []

    async def restart_deployment(
        self, namespace: str, deployment: str
    ) -> dict:
        action = {
            "type": "restart_deployment",
            "namespace": namespace,
            "deployment": deployment,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "status": "success",
            "message": f"deployment.apps/{deployment} restarted",
        }
        self.executed_actions.append(action)
        return action

    async def scale_deployment(
        self, namespace: str, deployment: str, replicas: int
    ) -> dict:
        action = {
            "type": "scale_deployment",
            "namespace": namespace,
            "deployment": deployment,
            "replicas": replicas,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "status": "success",
            "message": f"deployment.apps/{deployment} scaled to {replicas} replicas",
        }
        self.executed_actions.append(action)
        return action

    async def get_pods(
        self, namespace: str, label_selector: Optional[str] = None
    ) -> list[dict]:
        # Parse service name from label selector like "app=order-service"
        service = "unknown"
        if label_selector and "=" in label_selector:
            service = label_selector.split("=", 1)[1]

        rng = random.Random(42)
        pods = []
        for i in range(3):
            suffix = "".join(rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=5))
            rs_suffix = "".join(rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=9))
            pods.append({
                "name": f"{service}-{rs_suffix}-{suffix}",
                "namespace": namespace,
                "status": "Running",
                "restarts": 0,
                "age": "3d",
                "cpu": f"{rng.randint(10, 50)}m",
                "memory": f"{rng.randint(128, 512)}Mi",
            })
        return pods
