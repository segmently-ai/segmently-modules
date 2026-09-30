#!/bin/sh
# The modsys plugin's bin/modsys (tools/build_plugins.py installs this file there, mode 0755):
# runs the engine shipped in <plugin>/runtime with the first Python 3.11 or newer it finds —
# $MODSYS_PYTHON; else python3.14, python3.13, python3.12, python3.11, python3 on PATH; else the
# same names in the directories below, one directory at a time (outside $HOME: a sandbox that
# denies $HOME breaks pyenv and asdf shims); else `uv run`. Each candidate is run once to
# check its version; a name that is not there starts no process. POSIX sh (dash too).
DIRS="/opt/homebrew/bin /usr/local/bin /usr/bin"
NAMES="python3.14 python3.13 python3.12 python3.11 python3"
PROBE='import sys; sys.exit(sys.version_info < (3, 11))'

me=$0
while [ -h "$me" ]; do  # follow a symlink to this file: the plugin is where the file lives
    link=$(readlink "$me") || break
    case $link in
        /*) me=$link ;;
        *) case $me in */*) me=${me%/*}/$link ;; *) me=./$link ;; esac ;;
    esac
done
case $me in */*) bin=${me%/*} ;; *) bin=. ;; esac
root=$(cd -P "$bin/.." && pwd -P) || exit 127
PYTHONPATH="$root/runtime${PYTHONPATH:+:$PYTHONPATH}"  # the plugin's engine comes first
PYTHONDONTWRITEBYTECODE=1  # never write __pycache__ into the installed plugin
PYTHONSAFEPATH=1  # the working directory never shadows the plugin's engine (Python 3.11+)
export PYTHONPATH PYTHONDONTWRITEBYTECODE PYTHONSAFEPATH

if [ -n "${MODSYS_PYTHON:-}" ]; then  # an explicit choice: used, or a loud refusal
    if ! command -v "$MODSYS_PYTHON" >/dev/null 2>&1; then
        echo "modsys: MODSYS_PYTHON=$MODSYS_PYTHON: not found — unset it, or point it at" \
             "Python 3.11 or newer" >&2
        exit 127
    fi
    "$MODSYS_PYTHON" -c "$PROBE" </dev/null >/dev/null 2>&1
    rc=$?
    [ "$rc" -eq 0 ] && exec "$MODSYS_PYTHON" -m modsys "$@"
    if [ "$rc" -eq 1 ]; then why="is older than Python 3.11"; else why="does not run (exit $rc)"; fi
    echo "modsys: MODSYS_PYTHON=$MODSYS_PYTHON $why — unset it, or point it at Python 3.11" \
         "or newer" >&2
    exit 127
fi
for name in $NAMES; do
    py=$(command -v "$name" 2>/dev/null) || continue
    "$py" -c "$PROBE" </dev/null >/dev/null 2>&1 && exec "$py" -m modsys "$@"
done
for dir in $DIRS; do
    for name in $NAMES; do
        [ -x "$dir/$name" ] || continue
        "$dir/$name" -c "$PROBE" </dev/null >/dev/null 2>&1 && exec "$dir/$name" -m modsys "$@"
    done
done
if command -v uv >/dev/null 2>&1 && uv --version </dev/null >/dev/null 2>&1; then
    exec uv run --no-project --python '>=3.11' python -m modsys "$@"
fi
echo "modsys: no Python 3.11 or newer found — install Python 3.11 or newer, set MODSYS_PYTHON" \
     "to one, or install uv (it fetches a Python)" >&2
exit 127
