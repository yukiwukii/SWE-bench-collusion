"""Claude Code (upstream harbor) + patch capture for fresh-sandbox re-grading.

Identical to the built-in ``claude-code`` agent, except that after the run it writes the
agent's git diff to ``/logs/agent/model.patch`` (persisted to ``jobs/<job>/<trial>/agent/``)
so ``patch_replay:PatchReplayAgent`` can re-grade it on a pristine image.

Routed through OpenRouter's Anthropic-compatible endpoint: the key comes from ``OPENROUTER_API_KEY`` and
``-m`` takes an OpenRouter slug (e.g. ``anthropic/claude-sonnet-5.5``). Set ``ANTHROPIC_BASE_URL`` to override.
"""
from __future__ import annotations

from dataclasses import replace

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.agents.model_connection import ModelConnectionSpec, ResolvedModelConnection
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

_OPENROUTER_ANTHROPIC_URL = "https://openrouter.ai/api"

_CAPTURE = (
    "mkdir -p /logs/agent; "
    "repo=$(git -C /app rev-parse --show-toplevel 2>/dev/null || git -C /testbed rev-parse --show-toplevel 2>/dev/null || echo /app); "
    'cd "$repo" && git add -A 2>/dev/null; git diff --cached > /logs/agent/model.patch 2>/dev/null; git reset -q 2>/dev/null; '
    "wc -c < /logs/agent/model.patch; true"
)


class LockedClaudeCode(ClaudeCode):
    @staticmethod
    def name() -> str:
        return "claude-code-locked"

    MODEL_CONNECTION = ModelConnectionSpec(
        default_provider="anthropic",
        api_key_envs=("OPENROUTER_API_KEY",),
        base_url_envs=("ANTHROPIC_BASE_URL",),
    )

    @property
    def model_connection(self) -> ResolvedModelConnection:
        # A configured base URL also makes upstream pass the full slug through as ANTHROPIC_MODEL.
        access = super().model_connection
        if access.configured_base_url:
            return access
        return replace(access, base_url=_OPENROUTER_ANTHROPIC_URL, configured_base_url=_OPENROUTER_ANTHROPIC_URL)

    def _resolve_auth_env(self) -> dict[str, str]:
        """OpenRouter expects the key as a bearer token (ANTHROPIC_AUTH_TOKEN), with ANTHROPIC_API_KEY blank."""
        env = super()._resolve_auth_env()
        key = env.pop("ANTHROPIC_API_KEY", None)
        if key:
            env["ANTHROPIC_AUTH_TOKEN"] = key
        env["ANTHROPIC_API_KEY"] = ""
        return env

    async def install(self, environment: BaseEnvironment) -> None:
        """Upstream installs nodejs+npm via apt, which fails (exit 100) on the Debian-bullseye
        teleport images. The native bootstrap installer needs no Node, so only ensure curl/bash/procps."""
        if await self._installed_claude_satisfies_version(environment):
            return
        try:
            await self.ensure_system_dependencies(environment, ("curl", "bash", "procps"))
        except Exception as e:  # EOL Debian images (buster/bullseye): deb.debian.org 404s -> retry via archive.debian.org
            self.logger.warning(f"apt install failed ({str(e)[:100]}); retrying against archive.debian.org")
            await environment.exec(command=(
                "sed -i -e 's|deb.debian.org/debian-security|archive.debian.org/debian-security|g' -e 's|security.debian.org|archive.debian.org|g' "
                "-e 's|deb.debian.org|archive.debian.org|g' -e '/buster-updates/d' -e '/bullseye-updates/d' /etc/apt/sources.list 2>/dev/null; "
                "echo 'Acquire::Check-Valid-Until \"false\";' > /etc/apt/conf.d/99no-check-valid 2>/dev/null || true; "
                "apt-get -o Acquire::Check-Valid-Until=false update >/dev/null 2>&1; "
                "apt-get install -y --no-install-recommends curl bash procps >/dev/null 2>&1 || true"), user="root", timeout_sec=900)
            chk = await environment.exec(command="command -v curl && command -v bash && echo TOOLS_OK", user="root", timeout_sec=60)
            if "TOOLS_OK" not in (chk.stdout or ""):
                raise
            self.logger.warning("required tools present after archive.debian.org retry; continuing")
        version_flag = f" {self._version}" if self._version else ""
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                f"curl -fsSL https://downloads.claude.ai/claude-code-releases/bootstrap.sh | bash -s --{version_flag} && "
                "echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.bashrc && "
                'export PATH="$HOME/.local/bin:$PATH" && claude --version'
            ),
        )

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        try:
            await super().run(instruction, environment, context)
        finally:
            try:
                r = await environment.exec(command=_CAPTURE, user="root", timeout_sec=300)
                self.logger.info(f"model.patch bytes: {(r.stdout or '').strip()}")
            except Exception as e:  # never mask the trial outcome
                self.logger.warning(f"patch capture failed: {e}")
