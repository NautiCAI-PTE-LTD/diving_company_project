# Build and upload NautiCAI frontend to S3.
#
# Usage:
#   .\deploy\aws\deploy-ui.ps1 -Bucket nauticai-ui-prasad -ApiUrl http://YOUR_GCP_STATIC_IP:8000
#   .\deploy\aws\deploy-ui.ps1 -Bucket nauticai-ui-prasad -ApiUrl http://YOUR_GCP_STATIC_IP:8000 -DistributionId E1234ABCDEF
#
# If aws fails with InvalidAccessKeyId on PC, use AWS CloudShell:
#   bash deploy/aws/deploy-from-cloudshell.sh
param(
    [Parameter(Mandatory = $true)][string]$Bucket,
    [Parameter(Mandatory = $true)][string]$ApiUrl,
    [string]$DistributionId = "",
    [string]$FrontendDir = "F:\Diving_company_project\frontend"
)

$ErrorActionPreference = "Stop"
$ApiUrl = $ApiUrl.TrimEnd("/")

$envFile = Join-Path $FrontendDir ".env.production"
@"
VITE_API_URL=$ApiUrl
VITE_USE_MOCK=false
"@ | Set-Content -Path $envFile -Encoding UTF8

Push-Location $FrontendDir
try {
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    aws s3 sync dist/ "s3://$Bucket/" --delete
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($DistributionId) {
        aws cloudfront create-invalidation --distribution-id $DistributionId --paths "/*"
    }
    Write-Host ""
    Write-Host "Done. UI uploaded to s3://$Bucket/"
    Write-Host "API: $ApiUrl"
    Write-Host ""
    Write-Host "Test uploads: open S3 HTTP website (not CloudFront HTTPS unless API is HTTPS)."
    Write-Host "  Log in -> Settings -> Test health + upload -> Upload Raw Data -> Run AI on All"
    Write-Host "See deploy/aws/TEST-RAW-UPLOAD.md"
    if ($DistributionId) { Write-Host "CloudFront invalidation sent for $DistributionId" }
}
finally {
    Pop-Location
}
