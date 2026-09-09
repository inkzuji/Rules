#!/usr/bin/env bash
# CI 与本地 Linux x86_64 共用的固定版本安装入口。
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "用法: bash scripts/setup_mihomo.sh <安装目录>" >&2
  exit 1
fi
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo "此安装脚本仅支持 Linux x86_64；其他平台请使用官方 v1.19.30 二进制。" >&2
  exit 1
fi

version=v1.19.30
asset=mihomo-linux-amd64-v1-${version}.gz
sha256=cbe553d0319a414bd3a372c5976a252155b2c4882b66bce88a4d6bba9571a553
mihomo_work=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/rules-mihomo.XXXXXX")
curl --fail --location --retry 3 --connect-timeout 15 --max-time 180 \
  "https://github.com/MetaCubeX/mihomo/releases/download/${version}/${asset}" \
  --output "${mihomo_work}/${asset}"
printf '%s  %s\n' "$sha256" "${mihomo_work}/${asset}" | sha256sum --check --strict
gzip -dc "${mihomo_work}/${asset}" > "${mihomo_work}/mihomo"
mkdir -p "$1"
install -m 755 "${mihomo_work}/mihomo" "$1/mihomo"
"$1/mihomo" -v
