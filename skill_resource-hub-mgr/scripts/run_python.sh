#!/usr/bin/env bash
set -euo pipefail

# Require at least the target Python script path.
if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <script.py> [args...]" >&2
    exit 1
fi

# Save the script name, then shift so the remaining args can be passed through.
SCRIPT_NAME="$1"
shift

# Resolve absolute paths from this wrapper's location instead of the caller's cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${SKILL_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
REQUIREMENTS_FILE="${SKILL_DIR}/requirements.txt"
STAMP_FILE="${VENV_DIR}/.requirements.sha256"

# Create the skill-local virtualenv on first run, or if its Python is missing.
if [ ! -d "${VENV_DIR}" ] || [ ! -x "${VENV_PYTHON}" ]; then
    python3 -m venv "${VENV_DIR}"
fi

# Hash requirements.txt so we only reinstall dependencies when it changes.
# The inline Python reads the file path from argv[1] and prints a SHA-256 digest.
current_hash="$(
    python3 - "${REQUIREMENTS_FILE}" <<'PY'
import hashlib
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
if not path.exists():
    print("")
else:
    print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
)"

previous_hash=""
if [ -f "${STAMP_FILE}" ]; then
    previous_hash="$(cat "${STAMP_FILE}")"
fi

# Reinstall only when the requirements hash changed since the last run.
if [ "${current_hash}" != "${previous_hash}" ]; then
    if [ -f "${REQUIREMENTS_FILE}" ]; then
        "${VENV_PYTHON}" -m pip install --disable-pip-version-check -r "${REQUIREMENTS_FILE}" >/dev/null
    fi
    printf '%s' "${current_hash}" > "${STAMP_FILE}"
fi

# Accept either an absolute target script path or a path relative to scripts/.
case "${SCRIPT_NAME}" in
    /*)
        TARGET_SCRIPT="${SCRIPT_NAME}"
        ;;
    *)
        TARGET_SCRIPT="${SCRIPT_DIR}/${SCRIPT_NAME}"
        ;;
esac

if [ ! -f "${TARGET_SCRIPT}" ]; then
    echo "Script not found: ${TARGET_SCRIPT}" >&2
    exit 1
fi

# Replace this shell with the venv's Python process and forward all remaining args.
exec "${VENV_PYTHON}" "${TARGET_SCRIPT}" "$@"
