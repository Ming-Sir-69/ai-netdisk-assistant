#!/usr/bin/env bash
# Safe bootstrap: local checks by default; dependency installation is opt-in.

set -u

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
DEFAULT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)"
ROOT="${PANLIB_ROOT:-$DEFAULT_ROOT}"
VENV_DIR="${PANLIB_VENV_DIR:-$ROOT/.venv}"
PYTHON_BIN="${PANLIB_PYTHON_BIN:-${PYTHON_BIN:-python3}}"

OFFICIAL_REPO="https://github.com/baidu-netdisk/bdpan-storage"
OFFICIAL_INSTALLER_PAGE="https://github.com/baidu-netdisk/bdpan-storage/blob/main/skills/baidu-drive/scripts/install.sh"

usage() {
    cat <<'EOF'
Usage: scripts/bootstrap.sh [--install-deps]

Checks the local project environment without reading credentials.
  --install-deps  Explicitly allow pip to install requirements.txt into .venv.
  -h, --help      Show this help without running checks.
EOF
}

install_deps=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --install-deps) install_deps=1 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'bootstrap: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

venv_status="existing"
dependency_status="unknown"
bdpan_status="present"
next_steps=""

add_next() {
    if [ -n "$next_steps" ]; then
        next_steps="$next_steps|$1"
    else
        next_steps="$1"
    fi
}

modules_from_requirements() {
    local modules=""
    local distribution module
    for distribution in $(sed -nE 's/^[[:space:]]*([A-Za-z0-9_.-]+).*/\1/p' "$ROOT/requirements.txt" 2>/dev/null); do
        distribution="$(printf '%s' "$distribution" | tr '[:upper:]' '[:lower:]')"
        case "$distribution" in
            beautifulsoup4) module="bs4" ;;
            *) module="$(printf '%s' "$distribution" | tr '-' '_')" ;;
        esac
        modules="${modules:+$modules,}$module"
    done
    printf '%s' "$modules"
}

check_dependencies() {
    local required_modules dep_result dep_exit
    required_modules="${PANLIB_REQUIRED_MODULES:-}"
    if [ -z "$required_modules" ] && [ -f "$ROOT/requirements.txt" ]; then
        required_modules="$(modules_from_requirements)"
    fi
    if [ -z "$required_modules" ]; then
        dependency_status="ready"
        return
    fi
    dep_result="$("$VENV_PYTHON" -c 'import importlib.util,sys
mods = [item.strip() for item in sys.argv[1].split(",") if item.strip()]
missing = [item for item in mods if importlib.util.find_spec(item) is None]
sys.exit(1 if missing else 0)' "$required_modules" 2>/dev/null)"
    dep_exit=$?
    if [ "$dep_exit" -eq 0 ]; then
        dependency_status="ready"
    else
        dependency_status="missing"
    fi
}

python_version_status() {
    local value output exit_code version
    value="$1"
    output="$("$value" --version 2>&1)"
    exit_code=$?
    if [ "$exit_code" -ne 0 ]; then
        return 2
    fi
    version="$(printf '%s' "$output" | sed -nE 's/.*Python[[:space:]]+([0-9]+\.[0-9]+\.[0-9]+).*/\1/p')"
    if [ -z "$version" ]; then
        return 2
    fi
    if [ "$(printf '%s\n' "$version" | awk -F. '{ if ($1 > 3 || ($1 == 3 && $2 >= 13)) print "ok"; else print "old" }')" = "ok" ]; then
        return 0
    fi
    return 1
}

if [ -e "$VENV_DIR" ]; then
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        venv_status="invalid"
    else
        python_version_status "$VENV_DIR/bin/python"
        version_exit=$?
        if [ "$version_exit" -eq 1 ]; then
            venv_status="unsupported"
        elif [ "$version_exit" -ne 0 ]; then
            venv_status="invalid"
        fi
    fi
else
    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && [ ! -x "$PYTHON_BIN" ]; then
        venv_status="missing"
    else
        python_version_status "$PYTHON_BIN"
        version_exit=$?
        if [ "$version_exit" -eq 1 ]; then
            venv_status="unsupported"
        elif [ "$version_exit" -ne 0 ]; then
            venv_status="invalid"
        elif "$PYTHON_BIN" -m venv "$VENV_DIR" >/dev/null 2>&1; then
            venv_status="created"
        else
            venv_status="failed"
        fi
    fi
fi

VENV_PYTHON="$VENV_DIR/bin/python"
if [ "$venv_status" = "existing" ] || [ "$venv_status" = "created" ]; then
    if [ ! -x "$VENV_PYTHON" ]; then
        venv_status="invalid"
        dependency_status="blocked"
    else
        check_dependencies
        if [ "$dependency_status" = "missing" ] && [ "$install_deps" -eq 1 ]; then
            if [ -f "$ROOT/requirements.txt" ] && "$VENV_PYTHON" -m pip install -r "$ROOT/requirements.txt" >&2; then
                check_dependencies
            else
                dependency_status="install_failed"
            fi
        fi
    fi
else
    dependency_status="blocked"
fi

if [ "$venv_status" = "invalid" ]; then add_next "现有 .venv 不完整或 Python 不可执行；不会自动替换，请人工修复。"; fi
if [ "$venv_status" = "missing" ]; then add_next "未找到可用 Python；请先安装 Python 3.13+。"; fi
if [ "$venv_status" = "failed" ]; then add_next "创建 .venv 失败；请检查 Python 与目录权限。"; fi
if [ "$venv_status" = "unsupported" ]; then add_next "Python 版本不受支持；需要 3.13+，不会安装依赖。"; fi
if [ "$dependency_status" = "missing" ]; then add_next "依赖缺失；确认后重新运行 scripts/bootstrap.sh --install-deps。"; fi
if [ "$dependency_status" = "install_failed" ]; then add_next "依赖安装失败；未继续执行，请检查可信软件源和网络。"; fi

bdpan_cmd="${BDPAN_BIN:-bdpan}"
if ! command -v "$bdpan_cmd" >/dev/null 2>&1 && [ ! -x "$bdpan_cmd" ]; then
    bdpan_status="missing"
    add_next "bdpan 未安装；请从官方页面人工确认安装：${OFFICIAL_INSTALLER_PAGE}"
fi

overall="not_ready"
if { [ "$venv_status" = "existing" ] || [ "$venv_status" = "created" ]; } \
    && [ "$dependency_status" = "ready" ] && [ "$bdpan_status" = "present" ]; then
    overall="ready"
elif [ "$dependency_status" = "ready" ] && [ "$bdpan_status" = "missing" ]; then
    overall="missing_bdpan"
fi

printf '{"status":"%s","venv":{"status":"%s"},"dependencies":{"status":"%s"},"bdpan":{"status":"%s"},"next_steps":[' \
    "$overall" "$venv_status" "$dependency_status" "$bdpan_status"
if [ -n "$next_steps" ]; then
    old_ifs="$IFS"
    IFS='|'
    first=1
    for step in $next_steps; do
        if [ "$first" -eq 0 ]; then printf ','; fi
        printf '"%s"' "$step"
        first=0
    done
    IFS="$old_ifs"
fi
printf ']}\n'

if [ "$overall" = "ready" ]; then
    printf 'bootstrap: local checks complete; no credentials read.\n' >&2
    exit 0
fi
printf 'bootstrap: environment not ready; review structured next_steps. Official bdpan repository: %s\n' "$OFFICIAL_REPO" >&2
exit 1
