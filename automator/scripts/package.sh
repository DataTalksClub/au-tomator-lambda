#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

rm -rf "${PROJ_DIR}/package"
rm -f "${PROJ_DIR}/package.zip"

mkdir "${PROJ_DIR}/package"

# Install runtime deps into the package directory. We export the locked deps
# (from this project's own pyproject.toml/uv.lock) and pipe them into
# uv pip install --target, so versions stay in sync. boto3 is supplied by the
# Lambda runtime, so it lives in the dev group and is excluded here.
(cd "${PROJ_DIR}" && uv export --frozen --no-dev --no-emit-project --format requirements-txt) \
    | uv pip install --target "${PROJ_DIR}/package/" -r -

cp "${PROJ_DIR}/src/"*.py "${PROJ_DIR}/src/"*.yaml "${PROJ_DIR}/package/"

(cd "${PROJ_DIR}/package" && "${PYTHON_BIN}" -m zipfile -c ../package.zip *)

echo "Package created: ${PROJ_DIR}/package.zip"
