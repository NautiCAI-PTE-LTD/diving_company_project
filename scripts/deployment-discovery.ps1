# NautiCAI — deployment discovery (Windows / dev machine)
# Run from repo root:
#   powershell -ExecutionPolicy Bypass -File .\scripts\deployment-discovery.ps1
# Share the generated report file with your team.

param(
    [string]$OutFile = "",
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "SilentlyContinue"
if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
if (-not $OutFile) {
    $OutFile = Join-Path $RepoRoot "deployment-discovery-report.txt"
}

function Section($title) {
    "`n========== $title ==========`n"
}

$lines = @()
$lines += "NautiCAI deployment discovery report"
$lines += "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')"
$lines += "Host: $env:COMPUTERNAME"
$lines += "User: $env:USERNAME"
$lines += "Repo: $RepoRoot"

# --- OS ---
$lines += Section "Operating system"
$lines += (Get-CimInstance Win32_OperatingSystem | ForEach-Object {
    "Caption=$($_.Caption)"
    "Version=$($_.Version)"
    "Build=$($_.BuildNumber)"
    "Arch=$($_.OSArchitecture)"
})

# --- CPU / RAM ---
$lines += Section "CPU and memory"
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$lines += "CPU=$($cpu.Name)"
$lines += "LogicalProcessors=$($cpu.NumberOfLogicalProcessors)"
$cs = Get-CimInstance Win32_ComputerSystem
$lines += "RAM_GB=$([math]::Round($cs.TotalPhysicalMemory / 1GB, 2))"

# --- Disk ---
$lines += Section "Disk space"
Get-PSDrive -PSProvider FileSystem | ForEach-Object {
    $free = [math]::Round($_.Free / 1GB, 2)
    $used = [math]::Round(($_.Used) / 1GB, 2)
    $lines += "Drive $($_.Name): free=${free}GB used=${used}GB root=$($_.Root)"
}
$modelsPath = Join-Path $RepoRoot "Models"
if (Test-Path $modelsPath) {
    $size = (Get-ChildItem $modelsPath -Recurse -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
    $lines += "Models_folder_MB=$([math]::Round($size / 1MB, 1)) path=$modelsPath"
} else {
    $lines += "Models_folder=MISSING (upload ~172MB weights before deploy)"
}

# --- GPU ---
$lines += Section "GPU (NVIDIA)"
$nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidia) {
    $lines += (nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv 2>&1)
    $lines += "---"
    $lines += (nvidia-smi -L 2>&1)
} else {
    $lines += "nvidia-smi=not found (CPU-only deploy, or install NVIDIA driver)"
}

# --- Toolchain ---
$lines += Section "Toolchain"
foreach ($cmd in @(
    @{ Name = "git"; Args = "--version" },
    @{ Name = "python"; Args = "--version" },
    @{ Name = "node"; Args = "--version" },
    @{ Name = "npm"; Args = "--version" },
    @{ Name = "docker"; Args = "--version" }
)) {
    $c = Get-Command $cmd.Name -ErrorAction SilentlyContinue
    if ($c) {
        $out = & $cmd.Name $cmd.Args 2>&1 | Out-String
        $lines += "$($cmd.Name): $($out.Trim())"
    } else {
        $lines += "$($cmd.Name): not installed"
    }
}

# --- Docker state ---
$lines += Section "Docker"
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $lines += (docker info 2>&1 | Select-String -Pattern "Server Version|Operating System|Architecture|CPUs|Total Memory|Docker Root Dir" | ForEach-Object { $_.Line })
    $lines += "--- compose ---"
    $lines += (docker compose version 2>&1 | Out-String).Trim()
} else {
    $lines += "Docker not available"
}

# --- Local backend (if running) ---
$lines += Section "Local API probe"
foreach ($url in @("http://127.0.0.1:8000/api/health", "http://127.0.0.1:8000/api/system")) {
    try {
        $r = Invoke-RestMethod -Uri $url -TimeoutSec 3
        $lines += "$url OK: $($r | ConvertTo-Json -Compress -Depth 5)"
    } catch {
        $lines += "$url not reachable ($($_.Exception.Message))"
    }
}

# --- Network hint ---
$lines += Section "Network (outbound public IP)"
try {
    $ip = (Invoke-RestMethod -Uri "https://api.ipify.org?format=json" -TimeoutSec 5).ip
    $lines += "Public_IP=$ip (use for SSH allowlists / firewall notes)"
} catch {
    $lines += "Public_IP=unknown (offline or blocked)"
}

# --- Deployment questionnaire (fill in manually) ---
$lines += Section "YOUR ANSWERS (edit this file or reply in chat)"
$lines += @"
DEPLOY_TARGET=           # e.g. oracle-cloud | jetson | azure-vm | on-prem | laptop-demo
USERS_CONCURRENT=        # e.g. 1-5 divers, 10 inspectors
NEED_GPU=                # yes | no | unsure
DATABASE_CHOICE=         # supabase | oci-postgres | local-docker-postgres | sqlite-dev-only
DOMAIN_OR_IP=            # e.g. inspection.example.com or 203.0.113.10
HTTPS_REQUIRED=          # yes | no
FRONTEND_HOSTING=        # same-vm-nginx | vercel | cloudflare-pages | none-api-only
MODELS_READY=            # yes on this machine | need upload
AUTH_USERS=              # how many logins / need SSO?
STORAGE_GB_PER_MONTH=    # rough upload + report retention
BUDGET_NOTES=            # free tier / company OCI / etc.
"@

$text = $lines -join "`n"
$text | Set-Content -Path $OutFile -Encoding UTF8
Write-Host ""
Write-Host "Report written to: $OutFile"
Write-Host "Open it, fill in the YOUR ANSWERS section, and share the file (or paste contents) with your deploy contact."
Write-Host ""
