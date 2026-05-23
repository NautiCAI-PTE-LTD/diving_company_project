# Upload trained model weights to a GCS bucket (run from Windows dev machine).
#
# Prerequisites:
#   - gcloud CLI installed and logged in: gcloud auth login
#   - Models/*.pth, *.keras, *.pt present (see Models/README.md)
#
# Usage:
#   .\deploy\gcp-l4\upload-models-to-gcs.ps1 -Bucket nauticai-prod-artifacts
#   .\deploy\gcp-l4\upload-models-to-gcs.ps1 -Bucket nauticai-prod-artifacts -UploadBuilt
param(
    [Parameter(Mandatory = $true)][string]$Bucket,
    [string]$ProjectRoot = "F:\Diving_company_project",
    [switch]$UploadBuilt
)

$models = Join-Path $ProjectRoot "Models"
$required = @(
    "Ship_classification_v2.pth",
    "Before_and_after_v2.keras",
    "species_classifier_bundle.pt"
)

foreach ($f in $required) {
    $p = Join-Path $models $f
    if (-not (Test-Path $p)) {
        Write-Error "Missing $p — copy from Drive first (Models/README.md)."
        exit 1
    }
}

$prefix = "gs://$Bucket/models"
Write-Host "Uploading to $prefix/ ..."
foreach ($f in $required) {
    gcloud storage cp (Join-Path $models $f) "$prefix/"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($UploadBuilt) {
    $built = @(
        "Ship_classification_v2.onnx", "Ship_classification_v2.engine",
        "Before_and_after_v2.onnx", "Before_and_after_v2.engine",
        "species_classifier_bundle.onnx", "species_classifier_bundle.engine"
    )
    $dest = "gs://$Bucket/models-built"
    foreach ($f in $built) {
        $p = Join-Path $models $f
        if (Test-Path $p) {
            Write-Host "  $f"
            gcloud storage cp $p "$dest/"
        }
    }
    Write-Host "Optional built artefacts uploaded to $dest/"
}

Write-Host ""
Write-Host "Done. On the L4 VM run:"
Write-Host "  export GCS_BUCKET=$Bucket"
Write-Host "  ./deploy/gcp-l4/sync-from-gcs.sh"
