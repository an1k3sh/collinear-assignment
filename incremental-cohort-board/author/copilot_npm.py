"""Installation-only adapter; inference, options and resume remain Harbor-native."""
from harbor.agents.installed.copilot_cli import CopilotCli


class NpmCopilot(CopilotCli):
    async def install(self, environment):
        if self._version != "1.0.102":
            raise ValueError("Use the recorded CLI version 1.0.102")
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                'export PATH="$HOME/.local/bin:$PATH"; '
                "npm install -g --prefix \"$HOME/.local\" @github/copilot@1.0.102 "
                "--fetch-timeout=180000 --fetch-retries=2; "
                "copilot --version"
            ),
        )
