#!/bin/bash
set -euo pipefail

FUNCTION_NAME="${ROUTER_FUNCTION_NAME:-slack-test}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACKAGE_PATH="${PROJ_DIR}/package.zip"

if [[ "$OSTYPE" == "cygwin" || "$OSTYPE" == "msys" ]]; then
    PACKAGE_PATH=$(cygpath -w "${PACKAGE_PATH}")
fi

echo "Deploying router to AWS Lambda function: ${FUNCTION_NAME}"

aws lambda \
    update-function-code \
    --function-name "${FUNCTION_NAME}" \
    --zip-file "fileb://${PACKAGE_PATH}" \
        > /dev/null

echo "Router Lambda function updated successfully"
