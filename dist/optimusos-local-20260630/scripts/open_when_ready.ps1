[CmdletBinding()]
param(
    [string]$Url = "http://127.0.0.1:8000",
    [string]$HealthUrl = "http://127.0.0.1:8000/health",
    [string]$AccessToken = "",
    [int]$TimeoutSeconds = 45
)

$ErrorActionPreference = "SilentlyContinue"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)

while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $launchUrl = $Url
            if (-not [string]::IsNullOrWhiteSpace($AccessToken)) {
                # A URL fragment is never sent to the server or written to access logs.
                # The trusted local UI stores it in sessionStorage and immediately clears the fragment.
                $encodedToken = [uri]::EscapeDataString($AccessToken)
                $launchUrl = "$Url#access_token=$encodedToken"
            }
            Start-Process $launchUrl
            exit 0
        }
    }
    catch {
        Start-Sleep -Milliseconds 500
    }
}

exit 1
