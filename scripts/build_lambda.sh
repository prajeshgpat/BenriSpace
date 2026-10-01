#!/usr/bin/env bash
# Builds build/lambda.zip for the benrispace-api Lambda (python3.12, arm64).
#
# Dependencies are installed as prebuilt wheels for the TARGET platform
# (pip --platform/--python-version/--only-binary), never the host's, so the
# same zip comes out of macOS and of a GitHub Actions ubuntu runner without
# Docker. Nothing is compiled and no dependency code is executed.
#
# Set PIP_CONSTRAINT to a constraints file to pin versions (CI pins to the
# versions the test suite just ran against). PYTHON overrides the
# interpreter used to drive pip.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT/build"
STAGE_DIR="$BUILD_DIR/lambda"
ZIP_PATH="$BUILD_DIR/lambda.zip"
REQUIREMENTS="$BUILD_DIR/lambda-requirements.txt"

TARGET_PYTHON="3.12"
TARGET_ABI="cp312"
TARGET_MACHINE="aarch64"
# Lambda's python3.12 runtime is Amazon Linux 2023 (glibc 2.34), so wheels
# tagged up to manylinux_2_34 load. pip does not expand these, hence the
# explicit list, newest first.
TARGET_PLATFORMS=(
    "manylinux_2_34_${TARGET_MACHINE}"
    "manylinux_2_28_${TARGET_MACHINE}"
    "manylinux_2_17_${TARGET_MACHINE}"
    "manylinux2014_${TARGET_MACHINE}"
)

# What api.lambda_handler imports at runtime: api -> common, scoring.engine.
# ingestion/ and tests/ are not on that import graph.
APP_PACKAGES=(api common scoring)
# Declared in pyproject.toml for local dev but not needed on Lambda: Mangum
# replaces the ASGI server. boto3 is provided by the runtime and is only a
# dev dependency, so it never reaches the list in the first place.
EXCLUDED_DEPENDENCIES="uvicorn"

if [[ -n "${PYTHON:-}" ]]; then
    :
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    PYTHON="python3"
fi

rm -rf "$STAGE_DIR" "$ZIP_PATH"
mkdir -p "$STAGE_DIR"

"$PYTHON" - "$ROOT/pyproject.toml" "$REQUIREMENTS" "$EXCLUDED_DEPENDENCIES" <<'PY'
import re
import sys

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

pyproject, out_path, excluded = sys.argv[1], sys.argv[2], set(sys.argv[3].split())
with open(pyproject, "rb") as f:
    dependencies = tomllib.load(f)["project"]["dependencies"]


def name(requirement):
    return re.match(r"[A-Za-z0-9._-]+", requirement).group(0).lower().replace("_", "-")


kept = [d for d in dependencies if name(d) not in excluded]
missing = excluded - {name(d) for d in dependencies}
if missing:
    sys.exit(f"build_lambda: excluded dependencies not in pyproject.toml: {sorted(missing)}")
with open(out_path, "w") as f:
    f.write("\n".join(kept) + "\n")
PY

echo "==> Runtime requirements (pyproject.toml minus: $EXCLUDED_DEPENDENCIES)"
sed 's/^/    /' "$REQUIREMENTS"

platform_args=()
for platform in "${TARGET_PLATFORMS[@]}"; do
    platform_args+=(--platform "$platform")
done

echo "==> Installing wheels for CPython $TARGET_PYTHON / linux $TARGET_MACHINE"
"$PYTHON" -m pip install \
    --disable-pip-version-check \
    --quiet \
    --target "$STAGE_DIR" \
    --implementation cp \
    --python-version "$TARGET_PYTHON" \
    --abi "$TARGET_ABI" \
    "${platform_args[@]}" \
    --only-binary=:all: \
    --no-compile \
    --requirement "$REQUIREMENTS"

echo "==> Copying application packages: ${APP_PACKAGES[*]}"
for package in "${APP_PACKAGES[@]}"; do
    cp -R "$ROOT/$package" "$STAGE_DIR/$package"
done

# Console-script shims (fastapi, httpx, dotenv) are unusable on Lambda.
rm -rf "$STAGE_DIR/bin"
find "$STAGE_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$STAGE_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

echo "==> Verifying and zipping"
"$PYTHON" - "$STAGE_DIR" "$ZIP_PATH" "$TARGET_ABI" "$TARGET_MACHINE" <<'PY'
import os
import struct
import sys
import zipfile

stage, zip_path, abi, machine = sys.argv[1:5]
EM_AARCH64 = 183
ZIP_LIMIT = 50 * 1024 * 1024  # direct-upload limit for UpdateFunctionCode
UNZIPPED_LIMIT = 250 * 1024 * 1024

files = []
for dirpath, dirnames, filenames in os.walk(stage):
    dirnames.sort()
    for filename in sorted(filenames):
        path = os.path.join(dirpath, filename)
        files.append((os.path.relpath(path, stage).replace(os.sep, "/"), path))
files.sort()

# Every native library must be a Linux aarch64 ELF, and every extension
# module must be built for the target interpreter (or the stable ABI). A
# host-platform wheel slipping in would only show up as an ImportError on
# Lambda, after the deploy.
problems = []
native = 0
for arcname, path in files:
    basename = arcname.rsplit("/", 1)[-1]
    if not (basename.endswith((".so", ".dylib", ".pyd")) or ".so." in basename):
        continue
    native += 1
    with open(path, "rb") as f:
        header = f.read(20)
    if header[:4] != b"\x7fELF":
        problems.append(f"{arcname}: not an ELF binary")
        continue
    byteorder = "<" if header[5] == 1 else ">"
    (e_machine,) = struct.unpack(byteorder + "H", header[18:20])
    if header[4] != 2 or e_machine != EM_AARCH64:
        problems.append(f"{arcname}: ELF is not 64-bit {machine} (e_machine={e_machine})")
    interpreter_tag = basename.split(".")[1] if basename.count(".") >= 2 else ""
    if interpreter_tag.startswith(("cpython-", "cp3", "pypy")):
        expected = f"cpython-{abi[2:]}-{machine}-linux-gnu"
        if interpreter_tag != expected:
            problems.append(f"{arcname}: built for {interpreter_tag}, expected {expected}")

top_level = {arcname.split("/", 1)[0] for arcname, _ in files}
for required in ("api", "common", "scoring", "fastapi", "mangum", "pydantic_core", "psycopg_binary"):
    if required not in top_level:
        problems.append(f"expected package missing from the bundle: {required}")
for forbidden in ("uvicorn", "boto3", "botocore", "ingestion", "tests", "pytest", ".env"):
    if forbidden in top_level:
        problems.append(f"package must not be in the bundle: {forbidden}")
if native == 0:
    problems.append("no native extension modules found (psycopg/pydantic-core should have some)")

if problems:
    sys.exit("build_lambda: bundle verification failed:\n  " + "\n  ".join(problems))

# Fixed timestamps, permissions and ordering: identical inputs produce a
# byte-identical zip, so the function's CodeSha256 only changes when the
# code or a dependency version does.
unzipped = 0
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for arcname, path in files:
        info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = (0o100644) << 16
        with open(path, "rb") as f:
            data = f.read()
        unzipped += len(data)
        zf.writestr(info, data, compresslevel=9)

zipped = os.path.getsize(zip_path)
mb = 1024 * 1024
print(f"    {len(files)} files, {native} native libraries (all linux {machine})")
print(f"    zipped:   {zipped / mb:6.1f} MB  (limit {ZIP_LIMIT // mb} MB for direct upload)")
print(f"    unzipped: {unzipped / mb:6.1f} MB  (limit {UNZIPPED_LIMIT // mb} MB)")
if zipped > ZIP_LIMIT or unzipped > UNZIPPED_LIMIT:
    sys.exit("build_lambda: bundle exceeds Lambda's size limits")
PY

echo "==> Wrote ${ZIP_PATH#"$ROOT"/}"
