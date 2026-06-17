#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

rm -rf "${SCRIPT_DIR}/package"
rm -f "${SCRIPT_DIR}/package.zip"

mkdir "${SCRIPT_DIR}/package"

cp "${SCRIPT_DIR}"/*.py "${SCRIPT_DIR}/package/"
rm -f "${SCRIPT_DIR}"/package/test*.py

(cd "${SCRIPT_DIR}/package" && "${PYTHON_BIN}" -m zipfile -c ../package.zip *)

echo "Package created: ${SCRIPT_DIR}/package.zip"
