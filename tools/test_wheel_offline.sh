#!/bin/bash -e
# Install a Linux x86_64 wheel in a clean container, fill the runtime cache with
# 'fetch_runtime --all', then run the test suite in a container with no network.
# Usage: tools/test_wheel_offline.sh wheelhouse/libstempo-...-cp312-...manylinux...x86_64.whl

wheel=$(realpath "$1")
repo=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'docker run --rm -v "$work":/env python:3.12-slim rm -rf /env/venv /env/cache; rm -rf "$work"' EXIT

docker run --rm -v "$wheel":/wheel/$(basename "$wheel"):ro -v "$work":/env python:3.12-slim bash -ec "
  python -m venv /env/venv
  /env/venv/bin/pip install -q --root-user-action=ignore '/wheel/$(basename "$wheel")[astropy]' pytest
  LIBSTEMPO_CACHE_DIR=/env/cache /env/venv/bin/python -m libstempo.fetch_runtime --all"

docker run --rm --network none -v "$repo":/src:ro -v "$work":/env python:3.12-slim bash -ec "
  mkdir /t && cp -r /src/tests /src/install_tempo2.sh /t/ && cd /t
  LIBSTEMPO_CACHE_DIR=/env/cache /env/venv/bin/python -m pytest -q -p no:cacheprovider tests"
