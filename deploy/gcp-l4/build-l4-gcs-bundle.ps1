# Build nauticai-l4-gcs-bundle.zip for Google Cloud Storage (L4 GPU).
#
# L4 inference speed (see backend/inference/_runtime.py):
#   FASTEST  .engine   TensorRT FP16 (built on the L4 VM from .onnx)
#   FAST     .onnx     ONNX Runtime + CUDA  (~25-50 ms per photo)
#   SLOW     .pth/.pt/.keras  native PyTorch/Keras (~80-150 ms) - training formats only
#
# This zip includes:
#   - All three .onnx files when present (what the API uses on L4)
#   - Source checkpoints .pth, .keras, .pt (re-export + TensorRT build on VM)
#
# Usage:
#   .\deploy\gcp-l4\build-l4-gcs-bundle.ps1
param(
    [string]$ProjectRoot = "F:\Diving_company_project",
    [string]$OutputDir = "",
    [switch]$AllowNoOnnx
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $ProjectRoot
if (-not $OutputDir) {
    $OutputDir = Join-Path $Root "deploy\gcp-l4\dist"
}
$OutputDir = New-Item -ItemType Directory -Force -Path $OutputDir | Select-Object -ExpandProperty FullName

$modelsSrc = Join-Path $Root "Models"

# Canonical names from backend/config.py
$sourceRequired = @(
    @{ Name = "Ship_classification_v2.pth"; Role = "region"; Format = "PyTorch source" },
    @{ Name = "Before_and_after_v2.keras"; Role = "before_after"; Format = "Keras source" },
    @{ Name = "species_classifier_bundle.pt"; Role = "species"; Format = "PyTorch source" }
)

$onnxExpected = @(
    "Ship_classification_v2.onnx",
    "Before_and_after_v2.onnx",
    "species_classifier_bundle.onnx"
)

foreach ($item in $sourceRequired) {
    $p = Join-Path $modelsSrc $item.Name
    if (-not (Test-Path $p)) {
        Write-Error @"
Missing source checkpoint: $p

Copy model files from Drive into Models\ (see Models\README.md).
For L4 speed you also need ONNX exports - run on a machine with GPU/CPU:
  cd $Root
  .\.venv\Scripts\Activate.ps1
  `$env:NAUTICAI_BACKEND='native'
  python scripts\export_onnx.py
"@
    }
}

$missingOnnx = @()
foreach ($f in $onnxExpected) {
    if (-not (Test-Path (Join-Path $modelsSrc $f))) { $missingOnnx += $f }
}

if ($missingOnnx.Count -gt 0) {
    Write-Warning @"
ONNX files missing (L4 will be slower until export on VM):
  $($missingOnnx -join ', ')

Recommended before upload - export once locally:
  cd $Root
  .\.venv\Scripts\Activate.ps1
  `$env:NAUTICAI_BACKEND='native'
  python scripts\export_onnx.py
"@
    if (-not $AllowNoOnnx) {
        Write-Error "Export ONNX first, or pass -AllowNoOnnx to build a slow bundle (sources only)."
    }
}

$staging = Join-Path $env:TEMP "nauticai-l4-bundle-$(Get-Date -Format 'yyyyMMddHHmmss')"
New-Item -ItemType Directory -Force -Path "$staging\models" | Out-Null
New-Item -ItemType Directory -Force -Path "$staging\deploy\gcp-l4" | Out-Null

Write-Host "Staging L4 bundle (sources + ONNX for fast inference)..."

foreach ($item in $sourceRequired) {
    Copy-Item (Join-Path $modelsSrc $item.Name) "$staging\models\$($item.Name)"
    Write-Host "  + source $($item.Name)"
}

foreach ($f in $onnxExpected) {
    $p = Join-Path $modelsSrc $f
    if (Test-Path $p) {
        Copy-Item $p "$staging\models\$f"
        $mb = [math]::Round((Get-Item $p).Length / 1MB, 1)
        Write-Host "  + onnx   $f  (${mb} MB)  [L4 fast path]"
    }
}

# .engine files are built ON the Linux L4 VM only (not portable from Windows)
$engines = Get-ChildItem $modelsSrc -Filter "*.engine" -ErrorAction SilentlyContinue
if ($engines) {
    Write-Warning "Skipping .engine files - build TensorRT on the L4 VM (Linux), not from Windows."
}

$gcpScripts = @(
    "install-on-vm.sh",
    "SSH-INSTALL-NOW.sh",
    "setup_gpu_models.sh",
    "sync-from-gcs.sh",
    "bootstrap-gce.sh",
    "env.production.example",
    "nauticai-api.service",
    "README-GCS-ZIP.md",
    "MODEL-FORMATS-L4.md"
)
foreach ($s in $gcpScripts) {
    $src = Join-Path $Root "deploy\gcp-l4\$s"
    if (Test-Path $src) { Copy-Item $src "$staging\deploy\gcp-l4\$s" }
}

Copy-Item (Join-Path $Root "backend\requirements.txt") "$staging\requirements.txt"
Copy-Item (Join-Path $Root "backend\requirements-gpu.txt") "$staging\requirements-gpu.txt"

$manifest = @{
    built_at = (Get-Date).ToString("o")
    l4_runtime_priority = @(
        "1. .engine (TensorRT FP16) - build on VM: python scripts/build_trt.py --fp16",
        "2. .onnx (ONNX Runtime CUDA) - included in zip when exported",
        "3. .pth / .pt / .keras - fallback only (avoid on production L4)"
    )
    files = @()
}
Get-ChildItem "$staging\models" -File | ForEach-Object {
    $manifest.files += @{
        name = $_.Name
        size_mb = [math]::Round($_.Length / 1MB, 2)
        l4_use = if ($_.Extension -eq ".onnx") { "primary_inference" }
                 elseif ($_.Extension -eq ".engine") { "fastest_inference" }
                 else { "source_and_trt_build" }
    }
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content "$staging\MANIFEST.json" -Encoding UTF8

$readme = @(
    "NautiCAI L4 GCS bundle",
    "Built: $((Get-Date).ToString('o'))",
    "",
    "WHAT RUNS ON L4 (fastest first):",
    "  1) .engine  TensorRT (built on VM after unzip, 10-20 min once)",
    "  2) .onnx    ONNX Runtime + CUDA (included if exported before zipping)",
    "  3) .pth .pt .keras  slow fallback; kept for re-export / TRT pipeline only",
    "",
    "Upload: gcloud storage cp nauticai-l4-gcs-bundle.zip gs://YOUR_BUCKET/",
    "VM install: deploy/gcp-l4/README-GCS-ZIP.md"
)
$readme | Set-Content "$staging\README-FIRST.txt" -Encoding UTF8

$zipPath = Join-Path $OutputDir "nauticai-l4-gcs-bundle.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

Write-Host ""
Write-Host "Creating zip (may take 2-3 min)..."
Compress-Archive -Path "$staging\*" -DestinationPath $zipPath -CompressionLevel Optimal
Remove-Item -Recurse -Force $staging

$mb = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host ""
Write-Host ("Done: {0}  ({1} megabytes)" -f $zipPath, $mb)
Write-Host ""
Write-Host "L4 will use .onnx from the zip (fast). After install-on-vm.sh, optional TRT .engine is even faster."
Write-Host "Upload:"
Write-Host "  gcloud storage cp `"$zipPath`" gs://YOUR_BUCKET/nauticai-l4-gcs-bundle.zip"
