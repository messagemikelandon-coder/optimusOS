[CmdletBinding()]
param(
    [string]$Url = "http://127.0.0.1:8000/login",
    [string]$HealthUrl = "http://127.0.0.1:8000/health",
    [int]$TimeoutSeconds = 45
)

$ErrorActionPreference = "SilentlyContinue"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)

while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            Start-Process $Url
            exit 0
        }
    }
    catch {
        Start-Sleep -Milliseconds 500
    }
}

exit 1
