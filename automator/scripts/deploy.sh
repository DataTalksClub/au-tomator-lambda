#!/bin/bash
set -euo pipefail

FUNCTION_NAME="automator-process-reaction"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACKAGE_PATH="${PROJ_DIR}/package.zip"

if [[ "$OSTYPE" == "cygwin" || "$OSTYPE" == "msys" ]]; then
    PACKAGE_PATH=$(cygpath -w "${PACKAGE_PATH}")
fi

echo "Deploying ${FUNCTION_NAME} to AWS Lambda..."

aws lambda \
    update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --zip-file "fileb://${PACKAGE_PATH}" \
        > /dev/null

echo "${FUNCTION_NAME} updated successfully"
