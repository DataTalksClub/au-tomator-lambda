set -euo pipefail

rm -rf package
rm -f package.zip

mkdir package

# Install automator runtime deps into the package directory.
# We export the locked deps for the 'automator' extra and pipe them into
# uv pip install --target, so versions stay in sync with uv.lock.
uv export --frozen --no-dev --no-emit-project --extra automator --format requirements-txt \
    | uv pip install --target package/ -r -

cp automator/*.py automator/*.yaml package/

(cd package && zip -r ../package.zip *) > /dev/null

