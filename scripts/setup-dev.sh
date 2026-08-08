#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -n "${PANLIB_ROOT:-}" ]; then
    ROOT=$(CDPATH= cd -- "$PANLIB_ROOT" && pwd)
else
    ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
fi

if ! GIT_DIR=$(git -C "$ROOT" rev-parse --git-dir 2>/dev/null); then
    printf '%s\n' 'setup-dev: not a Git repository' >&2
    exit 2
fi
case "$GIT_DIR" in
    /*) ;;
    *) GIT_DIR="$ROOT/$GIT_DIR" ;;
esac
HOOK="$GIT_DIR/hooks/pre-commit"
mkdir -p "$(dirname -- "$HOOK")"

GUARD="$ROOT/scripts/privacy-guard"
if [ ! -f "$GUARD" ]; then
    printf '%s\n' 'setup-dev: scripts/privacy-guard is missing' >&2
    exit 2
fi
if [ ! -x "$GUARD" ]; then
    chmod u+x "$GUARD"
fi

MARKER_BEGIN='# >>> seedhub privacy-guard (managed) >>>'
MARKER_END='# <<< seedhub privacy-guard (managed) <<<'
if [ -f "$HOOK" ] && grep -Fq "$MARKER_BEGIN" "$HOOK"; then
    chmod u+x "$HOOK"
    printf '%s\n' 'setup-dev: privacy pre-commit already installed' >&2
    exit 0
fi

tmp_hook="$HOOK.tmp.$$"
trap 'rm -f "$tmp_hook"' EXIT HUP INT TERM

shebang='#!/bin/sh'
body_start=1
if [ -f "$HOOK" ]; then
    first_line=$(sed -n '1p' "$HOOK")
    case "$first_line" in
        '#!'*) shebang="$first_line"; body_start=2 ;;
    esac
fi

{
    printf '%s\n' "$shebang"
    printf '%s\n' "$MARKER_BEGIN"
    printf '%s\n' 'HOOK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)'
    printf '%s\n' 'if [ -x "$HOOK_ROOT/scripts/privacy-guard" ]; then'
    printf '%s\n' '    "$HOOK_ROOT/scripts/privacy-guard" --staged'
    printf '%s\n' 'else'
    printf '%s\n' '    python3 "$HOOK_ROOT/scripts/privacy-guard" --staged'
    printf '%s\n' 'fi'
    printf '%s\n' 'privacy_status=$?'
    printf '%s\n' '[ "$privacy_status" -eq 0 ] || exit "$privacy_status"'
    printf '%s\n' "$MARKER_END"
    if [ -f "$HOOK" ]; then
        if [ "$body_start" -eq 2 ]; then
            tail -n +2 "$HOOK"
        else
            cat "$HOOK"
        fi
    fi
} >"$tmp_hook"
chmod u+x "$tmp_hook"
mv "$tmp_hook" "$HOOK"
trap - EXIT HUP INT TERM

printf '%s\n' 'setup-dev: installed project-local privacy pre-commit' >&2
