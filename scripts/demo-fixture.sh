#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "$0")/.."
export PYTHONPATH=src
export PYTHONIOENCODING=utf-8

fixture=tests/fixtures/pilot-fake
out=output/fixture-demo

python -m learning_ingest extract --manifest "$fixture/manifest.yaml" --out "$out"
python -m learning_ingest prepare-review --manifest "$fixture/manifest.yaml" --out "$out"
python -m learning_ingest validate-export --input "$fixture/ai-output-valid.json" --out "$out"

printf 'Fixture demo outputs are in %s (review/ and export/).\n' "$out"
