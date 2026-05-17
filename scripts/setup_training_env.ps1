$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $repoRoot ".venv-train"
$python = Join-Path $venv "Scripts\python.exe"
$wheelDir = Join-Path $repoRoot ".cache\wheels"
$pipCache = Join-Path $repoRoot ".cache\pip"
$torchWheel = Join-Path $wheelDir "torch-2.11.0+cu130-cp310-cp310-win_amd64.whl"
$torchUrl = "https://download-r2.pytorch.org/whl/cu130/torch-2.11.0%2Bcu130-cp310-cp310-win_amd64.whl"

if (-not (Test-Path $python)) {
    py -3.10 -m venv $venv
}

New-Item -ItemType Directory -Force $wheelDir | Out-Null
New-Item -ItemType Directory -Force $pipCache | Out-Null

& $python -m pip install --upgrade pip wheel --cache-dir $pipCache
& $python -m pip install "setuptools<82" --cache-dir $pipCache

if (-not (Test-Path $torchWheel)) {
    curl.exe -L --retry 5 --retry-delay 5 --continue-at - -o $torchWheel $torchUrl
}

& $python -m pip install $torchWheel --cache-dir $pipCache
& $python -m pip install `
    torchvision==0.26.0+cu130 `
    torchaudio==2.11.0+cu130 `
    --extra-index-url https://download.pytorch.org/whl/cu130 `
    --cache-dir $pipCache
& $python -m pip install -r (Join-Path $repoRoot "requirements-training.txt") --cache-dir $pipCache

$env:PYTHONPATH = $repoRoot
@'
from agent.chains.model_training import detect_training_environment
import json
print(json.dumps(detect_training_environment(), ensure_ascii=False, indent=2))
'@ | & $python -
