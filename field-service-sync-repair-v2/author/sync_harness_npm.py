"""Harbor's unchanged Copilot adapter with an official npm installation transport."""
import shlex

from harbor.agents.installed.copilot_cli import CopilotCli
from harbor.environments.base import BaseEnvironment


class NpmInstalledCopilot(CopilotCli):
    async def install(self, environment: BaseEnvironment) -> None:
        if self._version != "1.0.102":
            raise ValueError("This experiment pins Copilot CLI 1.0.102")
        await self.ensure_system_dependencies(environment, ("curl", "bash", "git"))
        package = shlex.quote(f"@github/copilot@{self._version}")
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                f"npm install -g {package} --fetch-timeout=180000 --fetch-retries=2 && "
                "copilot --version"
            ),
        )
