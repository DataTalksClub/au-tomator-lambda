#!/bin/bash
set -euo pipefail

rm -rf package
rm -f package.zip

mkdir package

# Install moderator runtime deps into the package directory.
# We export the locked deps for the 'moderator' extra and pipe them into
# uv pip install --target. boto3 is provided by the Lambda runtime.
# Run from the repo root so uv can find pyproject.toml/uv.lock.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

(cd "${REPO_ROOT}" && uv export --frozen --no-dev --no-emit-project --extra moderator --format requirements-txt) \
    | uv pip install --target package/ -r -

# Copy moderator code
cp *.py package/

# Create zip package
(cd package && zip -r ../package.zip *) > /dev/null

echo "Package created: package.zip"
