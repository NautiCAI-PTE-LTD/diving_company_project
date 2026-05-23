# Upload Models + optional reference PDF to an Oracle Cloud VM.
# Usage:
#   .\deploy\oracle-cloud\upload-from-windows.ps1 -VmHost 129.x.x.x -User ubuntu -KeyPath C:\keys\oci.pem
param(
    [Parameter(Mandatory = $true)][string]$VmHost,
    [string]$User = "ubuntu",
    [string]$KeyPath = "",
    [string]$ProjectRoot = "F:\Diving_company_project",
    [string]$RemoteData = "/opt/nauticai/data"
)

$ssh = @("-o", "StrictHostKeyChecking=accept-new")
if ($KeyPath) { $ssh += @("-i", $KeyPath) }
$target = "${User}@${VmHost}"

$models = Join-Path $ProjectRoot "Models"
$required = @(
    "Ship_classification_v2.pth",
    "Before_and_after_v2.keras",
    "species_classifier_bundle.pt"
)
foreach ($f in $required) {
    if (-not (Test-Path (Join-Path $models $f))) {
        Write-Error "Missing $f under $models — copy from Drive first (see Models/README.md)."
        exit 1
    }
}

Write-Host "Creating remote directories…"
ssh @ssh $target "sudo mkdir -p $RemoteData/Models $RemoteData/storage && sudo chown -R ${User}:${User} /opt/nauticai"

Write-Host "Uploading model weights (~172 MB)…"
foreach ($f in $required) {
    scp @ssh (Join-Path $models $f) "${target}:${RemoteData}/Models/"
}

$pdf = Join-Path $ProjectRoot "Final Report - BW BIRCH - UWI, HC & PP in Fujairah, UAE.pdf"
if (Test-Path $pdf) {
    Write-Host "Uploading reference PDF…"
    scp @ssh $pdf "${target}:${RemoteData}/Final_Report_BW_BIRCH.pdf"
}

Write-Host "Done. On the VM, set in .env:"
Write-Host "  DATA_DIR=$RemoteData"
Write-Host "  REFERENCE_PDF=$RemoteData/Final_Report_BW_BIRCH.pdf"
Write-Host "  docker compose -f docker-compose.yml -f docker-compose.oci.yml up -d --build"
