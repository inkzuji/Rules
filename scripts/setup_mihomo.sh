#!/usr/bin/env bash
# CI Linux x86_64 与本机 macOS 共用的固定版本安装入口。
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "用法: bash scripts/setup_mihomo.sh <安装目录>" >&2
  exit 1
fi
version=v1.19.30
case "$(uname -s)/$(uname -m)" in
  Linux/x86_64)
    asset=mihomo-linux-amd64-v1-${version}.gz
    sha256=cbe553d0319a414bd3a372c5976a252155b2c4882b66bce88a4d6bba9571a553 ;;
  Darwin/x86_64)
    asset=mihomo-darwin-amd64-${version}.gz
    sha256=99dfcfe454ed58fb95ee4ba222c39defd051b687ad3e5deabb1b9d6be3103e2f ;;
  Darwin/arm64)
    asset=mihomo-darwin-arm64-${version}.gz
    sha256=2c7f3a7904fa1cee291e124123e630e7b1ebd13765dd9bf26c0a28432004d9f4 ;;
  *) echo "不支持的平台，请安装官方固定版本 ${version}" >&2; exit 1 ;;
esac
mihomo_work=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/rules-mihomo.XXXXXX")
curl --fail --location --retry 3 --connect-timeout 15 --max-time 180 \
  "https://github.com/MetaCubeX/mihomo/releases/download/${version}/${asset}" \
  --output "${mihomo_work}/${asset}"
actual=$(shasum -a 256 "${mihomo_work}/${asset}")
[[ "${actual%% *}" == "$sha256" ]] || { echo "SHA-256 校验失败" >&2; exit 1; }
gzip -dc "${mihomo_work}/${asset}" > "${mihomo_work}/mihomo"
mkdir -p "$1"
install -m 755 "${mihomo_work}/mihomo" "$1/mihomo"
"$1/mihomo" -v
