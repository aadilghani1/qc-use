# Install qc-use with uv, then register its skill for your coding agents.
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/aadilghani1/qc-use/main/install.ps1 | iex"
# QC_USE_SOURCE installs another source, such as a version (qc-use==0.3.0), a wheel, or a git URL.
$ErrorActionPreference = "Stop"

$source = if ($env:QC_USE_SOURCE) { $env:QC_USE_SOURCE } else { "qc-use" }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "qc-use: uv is missing. Installing uv from https://astral.sh/uv"
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

uv tool install --python 3.12 --upgrade $source
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$bin = (uv tool dir --bin).Trim()
& (Join-Path $bin "qc-use.exe") skill install
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $bin "qc-use.exe") --version

if (-not (($env:Path -split ";") -contains $bin)) {
    Write-Host "qc-use: $bin is not on your PATH. Run: uv tool update-shell"
}

Write-Host ""
Write-Host "Next:"
Write-Host "  1. Get a Vercel AI Gateway key: https://vercel.com/docs/ai-gateway"
Write-Host '  2. Try the demo:  $env:AI_GATEWAY_API_KEY="your-key"; qc-use demo --watch'
Write-Host '  3. Restart your coding agent and ask: "Test our signup critical path on localhost:3000."'
