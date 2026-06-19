#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

rm -rf "${PROJ_DIR}/package"
rm -f "${PROJ_DIR}/package.zip"

mkdir "${PROJ_DIR}/package"

# Router has no third-party runtime deps (boto3 is supplied by the Lambda
# runtime), so we just bundle the source.
cp "${PROJ_DIR}/src/"*.py "${PROJ_DIR}/package/"

(cd "${PROJ_DIR}/package" && "${PYTHON_BIN}" -m zipfile -c ../package.zip *)

echo "Package created: ${PROJ_DIR}/package.zip"
