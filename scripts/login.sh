#!/usr/bin/env bash
# Human-in-the-loop bdpan OAuth wrapper.

set -u

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
DEFAULT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)"
ROOT="${PANLIB_ROOT:-$DEFAULT_ROOT}"
BDPAN_BIN_VALUE="${BDPAN_BIN:-bdpan}"

usage() {
    cat <<'EOF'
Usage: scripts/login.sh

Opens Baidu's official OAuth page, accepts a hidden 32-character code through
stdin, and then runs the read-only doctor. No password or token is read.
  -h, --help  Show this help without contacting bdpan or the network.
EOF
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    "") ;;
    *) printf 'login: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
esac

if ! command -v "$BDPAN_BIN_VALUE" >/dev/null 2>&1 && [ ! -x "$BDPAN_BIN_VALUE" ]; then
    printf 'login: 未找到 bdpan；请先运行项目 scripts/bootstrap.sh 并人工安装官方依赖。\n' >&2
    exit 1
fi

TIMEOUT_PYTHON="${PANLIB_TIMEOUT_PYTHON:-}"
if [ -z "$TIMEOUT_PYTHON" ]; then
    TIMEOUT_PYTHON="python3"
fi
if ! command -v "$TIMEOUT_PYTHON" >/dev/null 2>&1 && [ ! -x "$TIMEOUT_PYTHON" ]; then
    printf 'login: 无可用 Python 超时保护；请先运行 scripts/bootstrap.sh。\n' >&2
    exit 1
fi
COMMAND_TIMEOUT="${PANLIB_COMMAND_TIMEOUT:-10}"
case "$COMMAND_TIMEOUT" in ""|*[!0-9]*) COMMAND_TIMEOUT=10 ;; esac

run_timed() {
    "$TIMEOUT_PYTHON" -c 'import subprocess,sys
data = sys.stdin.buffer.read()
try:
    result = subprocess.run(sys.argv[2:], input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=int(sys.argv[1]))
except subprocess.TimeoutExpired:
    sys.exit(124)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)' "$COMMAND_TIMEOUT" "$@"
}

if run_timed "$BDPAN_BIN_VALUE" whoami </dev/null >/dev/null 2>&1; then
    exec "$ROOT/bin/panlib-doctor"
else
    probe_exit=$?
    if [ "$probe_exit" -eq 124 ]; then
        printf 'login: bdpan 认证检查超时，未继续登录。\n' >&2
        exit 1
    fi
fi

printf '%s\n' '百度网盘 OAuth 登录需要你在官方网页中手动完成。请勿把账号、密码、验证码或 MFA 提供给代理。' >&2
printf '%s' '确认继续打开官方授权页面？输入 y 后回车（需要你手动确认）： ' >&2
IFS= read -r confirmation || confirmation=""
case "$confirmation" in
    y|Y|yes|YES|Yes) ;;
    *) printf '%s\n' 'login: 未确认，已退出；未执行登录。' >&2; exit 2 ;;
esac

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/panlib-login.XXXXXX")" || {
    printf '%s\n' 'login: 无法创建临时目录。' >&2
    exit 1
}
cleanup() {
    rm -rf -- "$tmp_dir"
}
trap cleanup EXIT
trap 'cleanup; exit 130' HUP INT TERM

if ! run_timed "$BDPAN_BIN_VALUE" login --get-auth-url --accept-disclaimer </dev/null >"$tmp_dir/auth.out" 2>"$tmp_dir/auth.err"; then
    printf '%s\n' 'login: bdpan 未能生成授权链接或命令超时；请稍后重试。' >&2
    exit 1
fi

auth_url="$(sed -nE 's#.*(https://[^[:space:]]+).*#\1#p' "$tmp_dir/auth.out" "$tmp_dir/auth.err" | head -n 1)"
case "$auth_url" in
    https://openapi.baidu.com/oauth/2.0/authorize\?*) ;;
    *) printf '%s\n' 'login: 授权地址并非百度官方 openapi OAuth 入口，已拒绝打开。' >&2; exit 1 ;;
esac

os_name="$(uname -s 2>/dev/null || printf 'Unknown')"
if [ "$os_name" = "Darwin" ]; then
    opener="${OPEN_BIN:-open}"
else
    opener="${OPEN_BIN:-xdg-open}"
fi
if command -v "$opener" >/dev/null 2>&1 || [ -x "$opener" ]; then
    "$opener" "$auth_url" >/dev/null 2>"$tmp_dir/open.err" || true
fi
printf '请在百度官方浏览器页面完成 OAuth（CAPTCHA/MFA 由你自行操作）：%s\n' "$auth_url" >&2

printf '%s' '授权完成后粘贴 32 位十六进制 code 并回车（输入隐藏）： ' >&2
IFS= read -r -s authorization_code || authorization_code=""
printf '\n' >&2
if [ "${#authorization_code}" -ne 32 ] || ! LC_ALL=C grep -Eq '^[0-9A-Fa-f]{32}$' <<<"$authorization_code"; then
    unset authorization_code
    printf '%s\n' 'login: code 格式无效；需要 32 位十六进制值。' >&2
    exit 2
fi

if ! run_timed "$BDPAN_BIN_VALUE" login --set-code-stdin --accept-disclaimer <<<"$authorization_code" >"$tmp_dir/set.out" 2>"$tmp_dir/set.err"; then
    unset authorization_code
    printf '%s\n' 'login: bdpan OAuth code 提交失败或超时；请重新运行。' >&2
    exit 1
fi
unset authorization_code

# exec does not run EXIT traps, so remove all captured output first.
cleanup
trap - EXIT HUP INT TERM
exec "$ROOT/bin/panlib-doctor"
