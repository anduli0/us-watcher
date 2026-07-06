# Regenerate the static snapshot from the live local API and publish it to the
# GitHub Pages CDN. The push triggers .github/workflows/deploy.yml, which
# rebuilds and redeploys the site (served 24/7, independent of this PC).
#
# Runs on residential IP so Yahoo/FRED/GoogleNews resolve to real data, and
# picks up the subscription-Claude prose the live server already generated.
#
# Usage:  powershell -ExecutionPolicy Bypass -File publish_static.ps1
$ErrorActionPreference = "Stop"
$repo = "C:\Users\andul\us-watcher"
Set-Location $repo

# 1) Snapshot the live API (must be up on :8088 via _usw-api.bat).
try {
    $null = Invoke-RestMethod "http://127.0.0.1:8088/health" -TimeoutSec 5
} catch {
    Write-Host "[publish] live API not reachable on :8088 - aborting (nothing to snapshot)."
    exit 1
}
$env:SNAPSHOT_API_BASE = "http://127.0.0.1:8088"
& "$repo\.venv\Scripts\python.exe" -m apps.snapshot.main
if ($LASTEXITCODE -ne 0) { throw "snapshot generator failed ($LASTEXITCODE)" }

# 2) Commit + push only if the baked data actually changed.
git add apps/web/public/data 2>$null
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "[publish] no snapshot changes - skipping push."
    exit 0
}
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm 'KST'"
git commit -m "snapshot: refresh static data ($stamp)" | Out-Null
git push origin main
Write-Host "[publish] pushed - GitHub Pages will redeploy in ~1 min."
