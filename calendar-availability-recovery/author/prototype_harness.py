"""Installation-only adaptation for Python task images; Copilot execution is inherited."""
from harbor.agents.installed.copilot_cli import CopilotCli
from harbor.environments.base import BaseEnvironment


class PrototypeCopilot(CopilotCli):
    async def install(self, environment: BaseEnvironment) -> None:
        if self._version != "1.0.102":
            raise ValueError("This experiment requires Copilot CLI 1.0.102")
        await self.ensure_system_dependencies(environment, ("curl", "bash", "git"))
        await self.exec_as_agent(
            environment,
            command=r"""
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
if ! command -v npm >/dev/null 2>&1; then
  case "$(uname -m)" in
    aarch64|arm64) node_archive=node-v22.14.0-linux-arm64.tar.gz ;;
    x86_64|amd64) node_archive=node-v22.14.0-linux-x64.tar.gz ;;
    *) echo 'Unsupported Node architecture' >&2; exit 1 ;;
  esac
  staging="$(mktemp -d)"
  (
    cd "$staging"
    curl -fsSL --retry 3 --connect-timeout 15 --max-time 300 \
      "https://nodejs.org/dist/v22.14.0/$node_archive" -o "$node_archive"
    curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 \
      https://nodejs.org/dist/v22.14.0/SHASUMS256.txt -o SHASUMS256.txt
    grep "  $node_archive\$" SHASUMS256.txt | sha256sum --check --strict
    mkdir -p "$HOME/.local"
    tar -xzf "$node_archive" --strip-components=1 -C "$HOME/.local"
    rm "$node_archive" SHASUMS256.txt
  )
  rmdir "$staging"
fi
node --version
npm install -g --prefix "$HOME/.local" @github/copilot@1.0.102 \
  --fetch-timeout=180000 --fetch-retries=2
copilot --version
""",
        )
