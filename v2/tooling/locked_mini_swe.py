"""mini-swe-agent (upstream harbor built-in, runs inside the sandbox) + model.patch capture,
for fresh-sandbox re-grading with patch_replay:PatchReplayAgent."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from harbor.agents.installed.mini_swe_agent import MiniSweAgent
from openrouter_pricing import litellm_registry
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

# Model class that bills each call at OpenRouter's reported cost (see configs/mini_toolcall.yaml: model_class).
_SANDBOX_MODULE = Path(__file__).parent / "sandbox" / "sbp_openrouter_model.py"
_SANDBOX_DIR = "/opt/sbp"

_CAPTURE = (
    "pkill -f '[m]ini-swe-agent --yolo' >/dev/null 2>&1; sleep 3; "  # stop the agent so the trajectory file is not still being written when harbor tars /logs/agent
    "mkdir -p /logs/agent; "
    "repo=$(git -C /app rev-parse --show-toplevel 2>/dev/null || git -C /testbed rev-parse --show-toplevel 2>/dev/null || echo /app); "
    'cd "$repo" && git add -A 2>/dev/null; git diff --cached > /logs/agent/model.patch 2>/dev/null; git reset -q 2>/dev/null; '
    "wc -c < /logs/agent/model.patch; true"
)


class LockedMiniSwe(MiniSweAgent):
    def __init__(self, *args, **kwargs):
        """LiteLLM has no prices for most OpenRouter models. Register the model's OpenRouter list prices as a
        fallback for responses without usage.cost (the sandbox model class prefers OpenRouter's billed cost)."""
        model_name = kwargs.get("model_name") or ""
        if (model_name.startswith("openrouter/") and kwargs.get("litellm_model_registry") is None
                and not kwargs.get("litellm_model_registry_file")):
            try:
                kwargs["litellm_model_registry"] = litellm_registry(model_name)
            except Exception as e:
                logging.getLogger(__name__).warning(f"no OpenRouter pricing for {model_name}: {e}; cost_limit inactive")
        # Optional per-experiment OpenRouter provider routing (https://openrouter.ai/docs/features/provider-routing),
        # e.g. {order: [baidu], sort: price}; replaces model.model_kwargs.extra_body.provider from the config file.
        provider = kwargs.pop("openrouter_provider", None)
        if provider is not None:
            config_file = kwargs.pop("config_file", None)
            config = kwargs.pop("config", None) or (yaml.safe_load(Path(config_file).read_text()) if config_file else {})
            config.setdefault("model", {}).setdefault("model_kwargs", {}).setdefault("extra_body", {})["provider"] = provider
            kwargs["config"] = config
        # Upstream defaults cost_limit to "0" and always passes `--cost-limit 0`, which overrides the config
        # file's agent.cost_limit and disables the cap. Omit the flag unless a cost_limit kwarg is given.
        kwargs.setdefault("cost_limit", None)
        super().__init__(*args, **kwargs)

    @staticmethod
    def name() -> str:
        return "mini-swe-agent-locked"

    async def install(self, environment: BaseEnvironment) -> None:
        """Upstream installs against the image's system Python; on the Python-3.10 SWE-bench Pro
        images the newest litellm then fails to import (typing.NotRequired). Pin a managed 3.12."""
        try:
            await self.ensure_system_dependencies(
                environment, ("curl", "bash", "build_tools", "git", "python3", "python_pip"))
        except Exception as e:  # old Debian images (buster/bullseye): deb.debian.org no longer serves them -> retry via archive.debian.org
            self.logger.warning(f"apt install failed ({str(e)[:100]}); retrying against archive.debian.org")
            await environment.exec(command=(
                "sed -i -e 's|deb.debian.org/debian-security|archive.debian.org/debian-security|g' -e 's|security.debian.org|archive.debian.org|g' "
                "-e 's|deb.debian.org|archive.debian.org|g' -e '/buster-updates/d' -e '/bullseye-updates/d' /etc/apt/sources.list 2>/dev/null; "
                "echo 'Acquire::Check-Valid-Until \"false\";' > /etc/apt/conf.d/99no-check-valid 2>/dev/null || true; "
                "apt-get -o Acquire::Check-Valid-Until=false update >/dev/null 2>&1; "
                "apt-get install -y --no-install-recommends curl bash git python3 python3-pip build-essential >/dev/null 2>&1 || true"), user="root", timeout_sec=900)
            chk = await environment.exec(command="command -v curl && command -v git && command -v bash && echo TOOLS_OK", user="root", timeout_sec=60)
            if "TOOLS_OK" not in (chk.stdout or ""):
                raise
            self.logger.warning("required tools present after archive.debian.org retry; continuing")
        version_spec = f"=={self._version}" if self._version else ""
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                "if ! command -v uv >/dev/null 2>&1; then curl -LsSf https://astral.sh/uv/install.sh | sh; fi && "
                'if ! grep -q \'export PATH="$HOME/.local/bin:$PATH"\' "$HOME/.bashrc" 2>/dev/null; then'
                '  echo \'export PATH="$HOME/.local/bin:$PATH"\' >> "$HOME/.bashrc"; fi && '
                'if [ -f "$HOME/.local/bin/env" ]; then source "$HOME/.local/bin/env"; fi && '
                'export PATH="$HOME/.local/bin:$PATH" && '
                f"uv tool install --python 3.12 mini-swe-agent{version_spec} "
                "--with litellm --with orjson --with fastapi && mini-swe-agent --help"
            ),
        )


    async def exec_as_agent(self, environment, command: str, **kw):
        """Wrap the mini-swe-agent invocation in an in-sandbox `timeout` (budget - 60 s) so the process
        always ends even if harbor's client-side timeout cannot cancel a stalled exec stream.

        Also use LiteLLM's bundled cost map: the agent sandbox is offline, and LiteLLM's remote cost-map
        fetch + background retry crashes mini-swe-agent at import (circular import in litellm 1.105)."""
        kw["env"] = {"LITELLM_LOCAL_MODEL_COST_MAP": "True", "PYTHONPATH": _SANDBOX_DIR, **(kw.get("env") or {})}
        if "mini-swe-agent --yolo" in command:
            budget = int(getattr(self, "_timeout_sec", None) or 3000) - 60
            command = f"timeout -k 30 {budget} bash -c {__import__('shlex').quote(command)}"
        return await super().exec_as_agent(environment, command, **kw)

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        await environment.exec(command=f"mkdir -p {_SANDBOX_DIR}", user="root", timeout_sec=60)
        await environment.upload_file(source_path=_SANDBOX_MODULE, target_path=f"{_SANDBOX_DIR}/{_SANDBOX_MODULE.name}")
        await environment.exec(command=f"chmod -R a+rX {_SANDBOX_DIR}", user="root", timeout_sec=60)
        try:
            await super().run(instruction, environment, context)
        finally:
            try:
                r = await environment.exec(command=_CAPTURE, user="root", timeout_sec=300)
                self.logger.info(f"model.patch bytes: {(r.stdout or '').strip()}")
            except Exception as e:
                self.logger.warning(f"patch capture failed: {e}")
