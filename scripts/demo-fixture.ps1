$ErrorActionPreference = 'Stop'
$previousPythonPath = $env:PYTHONPATH
$previousPythonEncoding = $env:PYTHONIOENCODING

Push-Location -LiteralPath (Join-Path $PSScriptRoot '..')
try {
    $env:PYTHONPATH = 'src'
    $env:PYTHONIOENCODING = 'utf-8'
    $fixture = 'tests/fixtures/pilot-fake'
    $out = 'output/fixture-demo'

    python -m learning_ingest extract --manifest "$fixture/manifest.yaml" --out $out
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    python -m learning_ingest prepare-review --manifest "$fixture/manifest.yaml" --out $out
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    python -m learning_ingest validate-export --input "$fixture/ai-output-valid.json" --out $out
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Output "Fixture demo outputs are in $out (review/ and export/)."
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONIOENCODING = $previousPythonEncoding
    Pop-Location
}
