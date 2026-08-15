#!/usr/bin/env bash
set -u

# Deterministic, read-only readiness gate for every Agent host.  It does not
# open a browser or request a credential; it proves that this process can read
# the secure store and that the official Baidu MCP can list the real root.

root="${PANLIB_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
python_bin="$root/.venv/bin/python"
doctor="$root/bin/panlib-doctor"
library="$root/bin/panlib-library"

blocked() {
  printf '%s\n' '{"status":"blocked","check":"host_full_access","next_step":"在 Codex、WorkBuddy 或当前 Agent 宿主中开启完全访问，确保可访问 macOS 钥匙串、百度 MCP 和百度网盘网络；然后重跑 scripts/preflight.sh。"}'
  exit 1
}

if [ ! -x "$python_bin" ] || [ ! -x "$doctor" ] || [ ! -f "$library" ]; then
  blocked
fi

if ! "$doctor" >/dev/null 2>&1; then
  blocked
fi

auth_output=$("$python_bin" "$library" auth-status 2>/dev/null) || blocked
case "$auth_output" in
  *'"configured": true'*|*'"configured":true'*) ;;
  *) blocked ;;
esac

if ! "$python_bin" "$library" list --path / >/dev/null 2>&1; then
  blocked
fi

printf '%s\n' '{"status":"ready","checks":{"local":"ready","secure_credential":"ready","full_drive_read":"ready"},"browser_opened":false}'
