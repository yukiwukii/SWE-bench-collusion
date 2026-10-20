#!/usr/bin/env bash
# Prepare a fresh Ubuntu 24.04 server (target: Hetzner CPX62) to run experiments on local Docker.
# Run on the server as root; vm.sh setup does this for you. Safe to re-run.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -q
apt-get install -yq curl git python3 rsync tmux

command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
# Every sandbox gets its own compose network. Docker's default address pools run out after ~30 networks,
# which many concurrent trials can reach, so give it room for ~1000.
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{"default-address-pools": [{"base": "10.200.0.0/14", "size": 24}]}
EOF
systemctl restart docker

# Swap, so a memory spike in one sandbox slows the box down instead of getting a container OOM-killed.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 16G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
# Same versions as the machine that ran the stage 1 pilot. litellm is pinned too: 1.106.0 (2026-10-18) imports the
# optional mcp package on every completion call, so every agent died on its first call.
uv tool install --force --python 3.13 "harbor==0.24.0" --with "mini-swe-agent==2.4.6" --with "litellm==1.105.1"

docker info --format 'docker {{.ServerVersion}}, {{.NCPU}} CPU, {{.MemTotal}} bytes RAM'
harbor --version
df -h / | tail -1
echo "setup done"
