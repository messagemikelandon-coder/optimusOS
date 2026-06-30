[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $ProjectRoot ".env"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Read-HiddenText([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function Set-DotEnvValue([string]$Name, [string]$Value) {
    $lines = if (Test-Path $EnvPath) { [System.IO.File]::ReadAllLines($EnvPath) } else { @() }
    $replacement = "$Name=$Value"
    $found = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index].StartsWith("$Name=", [System.StringComparison]::OrdinalIgnoreCase)) {
            $lines[$index] = $replacement
            $found = $true
        }
    }
    if (-not $found) { $lines += $replacement }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($EnvPath, $lines, $encoding)
}

Set-Location $ProjectRoot
if (-not (Test-Path $VenvPython)) {
    throw "Optimus is not installed. Run WINDOWS_SETUP.bat first."
}

Write-Host "Paste a STANDARD PROJECT API KEY from the OpenAI API Keys page." -ForegroundColor Cyan
Write-Host "Do not paste an Optimus token, Admin API key, 'Bearer ', or OPENAI_API_KEY=."
$key = (Read-HiddenText "New OPENAI_API_KEY").Trim()

if ([string]::IsNullOrWhiteSpace($key)) { throw "No key was entered." }
if ($key.StartsWith("Bearer ", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Remove 'Bearer ' and enter only the key."
}
if ($key.StartsWith("OPENAI_API_KEY=", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Remove 'OPENAI_API_KEY=' and enter only the key."
}
if ($key -match "\s") { throw "The key contains whitespace or a line break." }

Set-DotEnvValue "OPENAI_API_KEY" $key
Write-Host "Saved the new key to .env." -ForegroundColor Green

$userKey = [Environment]::GetEnvironmentVariable("OPENAI_API_KEY", "User")
$machineKey = [Environment]::GetEnvironmentVariable("OPENAI_API_KEY", "Machine")
if (-not [string]::IsNullOrWhiteSpace($userKey) -or -not [string]::IsNullOrWhiteSpace($machineKey)) {
    Write-Warning "Windows also has an OPENAI_API_KEY variable. Optimus 7.0.1 ignores it and uses .env."
}

& $VenvPython (Join-Path $ProjectRoot "scripts\diagnose_openai_config.py")
if ($LASTEXITCODE -ne 0) { throw "Configuration diagnostic failed." }

& $VenvPython (Join-Path $ProjectRoot "scripts\check_openai.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "OpenAI connection accepted." -ForegroundColor Green
