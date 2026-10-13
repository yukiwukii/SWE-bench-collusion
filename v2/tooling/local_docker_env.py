"""Harbor docker environment for hosts whose Docker kernel lacks nftables ``fib inet`` (e.g. Docker Desktop on
macOS). There Harbor cannot start its egress-control sidecar and rejects every task with
``network_mode = "no-network"``, which includes all SWE-bench Pro agent phases.

This subclass enforces the two policies these tasks use without the sidecar:
  no-network  disconnect the main container from every Docker network (only loopback is left)
  public      reconnect it to the networks it had at start
Allowlists are not supported. Use in a job config::

    environment:
      import_path: local_docker_env:OfflineCapableDocker
"""
from __future__ import annotations

import asyncio
import json

from harbor.constants import MAIN_SERVICE_NAME
from harbor.environments.capabilities import EnvironmentCapabilities
from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import NetworkMode, NetworkPolicy


class OfflineCapableDocker(DockerEnvironment):
    _saved_networks: list[str] | None = None

    @property
    def capabilities(self) -> EnvironmentCapabilities:
        caps = super().capabilities
        if self._enable_egress_control:  # kernel supports the sidecar: use Harbor's own enforcement
            return caps
        return caps.model_copy(update={"disable_internet": True, "dynamic_network_policy": True})

    async def start(self, force_build: bool):
        await super().start(force_build)
        if not self._enable_egress_control and self._network_policy.network_mode != NetworkMode.PUBLIC:
            await self._apply_network_policy(self._network_policy)

    async def _docker(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec("docker", *args, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"docker {' '.join(args)} failed: {err.decode()[:300]}")
        return out.decode()

    async def _main_container(self) -> str:
        r = await self._run_docker_compose_command(["ps", "-q", MAIN_SERVICE_NAME])
        cid = (r.stdout or "").strip().splitlines()
        if not cid:
            raise RuntimeError("main container not found")
        return cid[0]

    async def _apply_network_policy(self, network_policy: NetworkPolicy) -> None:
        if self._enable_egress_control:
            return await super()._apply_network_policy(network_policy)
        cid = await self._main_container()
        if network_policy.network_mode == NetworkMode.NO_NETWORK:
            nets = json.loads(await self._docker("inspect", "-f", "{{json .NetworkSettings.Networks}}", cid)) or {}
            self._saved_networks = (self._saved_networks or []) + [n for n in nets if n != "none"]
            for n in nets:
                if n != "none":
                    await self._docker("network", "disconnect", "-f", n, cid)
            self.logger.info(f"network disconnected ({', '.join(nets) or 'none'})")
        elif network_policy.network_mode == NetworkMode.PUBLIC:
            for n in self._saved_networks or []:
                await self._docker("network", "connect", n, cid)
            self.logger.info(f"network reconnected ({', '.join(self._saved_networks or []) or 'none'})")
            self._saved_networks = None
        else:
            raise ValueError(f"{type(self).__name__} supports only no-network and public, not "
                             f"{network_policy.network_mode}")
