param(
    [string]$Python = "",
    [switch]$ForceRecreate
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $ProjectRoot ".venv-ocr"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Lock = Join-Path $ProjectRoot "requirements-ocr.lock"
$ModelDir = Join-Path $ProjectRoot "models\ocr\PP-OCRv5_mobile_rec_infer"

if ($ForceRecreate -and (Test-Path -LiteralPath $Venv)) {
    Remove-Item -LiteralPath $Venv -Recurse -Force
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    if ($Python) {
        $BasePython = $Python
    } else {
        $py = Get-Command py -ErrorAction SilentlyContinue
        if ($py) {
            & $py.Source -3.11 -m venv $Venv
            if ($LASTEXITCODE -ne 0) { throw "failed to create .venv-ocr with py -3.11" }
            $BasePython = $null
        } else {
            $pythonCmd = Get-Command python -ErrorAction Stop
            $BasePython = $pythonCmd.Source
        }
    }
    if ($BasePython) {
        & $BasePython -m venv $Venv
        if ($LASTEXITCODE -ne 0) { throw "failed to create .venv-ocr with $BasePython" }
    }
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "ShuaBao OCR virtualenv was not created: $VenvPython"
}

Write-Host "[ShuaBao OCR] installing locked runtime ..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $Lock
if ($LASTEXITCODE -ne 0) { throw "OCR dependency installation failed" }

Write-Host "[ShuaBao OCR] validating imports ..." -ForegroundColor Cyan
& $VenvPython -c "import paddle, paddleocr, paddlex; print('paddle', paddle.__version__); print('paddleocr', paddleocr.__version__); print('paddlex', paddlex.__version__)"
if ($LASTEXITCODE -ne 0) { throw "OCR import validation failed" }

if (-not (Test-Path -LiteralPath $ModelDir)) {
    throw "OCR model is missing: $ModelDir"
}

$env:SHUABAO_OCR_PYTHON = $VenvPython
$env:SHUABAO_OCR_MODEL_DIR = Join-Path $ProjectRoot "models\ocr"
$env:SHUABAO_OCR_REPO_ROOT = $ProjectRoot

Write-Host "[ShuaBao OCR] runtime ready" -ForegroundColor Green
Write-Host "python: $VenvPython"
Write-Host "model : $ModelDir"
Write-Host "Note: environment variables above apply to this PowerShell process only; normal LIVE discovery also finds $VenvPython automatically."
