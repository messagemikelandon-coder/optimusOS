[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$EnvPath = Join-Path $ProjectRoot ".env"
$EnvExamplePath = Join-Path $ProjectRoot ".env.example"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-PythonVersion([string]$Executable, [string[]]$PrefixArguments) {
    try {
        $arguments = @($PrefixArguments) + @(
            "-c",
            "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 14) else 1)"
        )
        & $Executable @arguments 2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Find-CompatiblePython {
    $py = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        if (Test-PythonVersion -Executable $py.Source -PrefixArguments @("-3.12")) {
            return [PSCustomObject]@{ Executable = $py.Source; Prefix = @("-3.12") }
        }
        if (Test-PythonVersion -Executable $py.Source -PrefixArguments @("-3.13")) {
            return [PSCustomObject]@{ Executable = $py.Source; Prefix = @("-3.13") }
        }
    }

    foreach ($name in @("python.exe", "python3.exe")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $command -and (Test-PythonVersion -Executable $command.Source -PrefixArguments @())) {
            return [PSCustomObject]@{ Executable = $command.Source; Prefix = @() }
        }
    }

    throw @"
Python 3.12 or 3.13 was not found.
Install 64-bit Python 3.12 from python.org and enable these installer options:
  - Add python.exe to PATH
  - Install launcher for all users
Then run WINDOWS_SETUP.bat again.
"@
}

function Invoke-SystemPython([object]$Python, [string[]]$Arguments) {
    $allArguments = @($Python.Prefix) + $Arguments
    & $Python.Executable @allArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
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

    if (-not $found) {
        $lines += $replacement
    }

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($EnvPath, $lines, $encoding)
}

function Get-DotEnvValue([string]$Name) {
    if (-not (Test-Path $EnvPath)) { return "" }
    foreach ($line in [System.IO.File]::ReadAllLines($EnvPath)) {
        if ($line.StartsWith("$Name=", [System.StringComparison]::OrdinalIgnoreCase)) {
            return $line.Substring($Name.Length + 1).Trim()
        }
    }
    return ""
}

function Set-DotEnvDefault([string]$Name, [string]$Value) {
    $current = Get-DotEnvValue $Name
    if ([string]::IsNullOrWhiteSpace($current)) {
        Set-DotEnvValue $Name $Value
    }
}

function Read-HiddenText([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

Set-Location $ProjectRoot
Write-Step "Locating Python 3.12 or 3.13"
$Python = Find-CompatiblePython
$versionArguments = @($Python.Prefix) + @("--version")
$PythonVersion = (& $Python.Executable @versionArguments 2>&1 | Out-String).Trim()
Write-Host "Using $PythonVersion"

$createVenv = -not (Test-Path $VenvPython)
if (-not $createVenv) {
    & $VenvPython -c "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 14) else 1)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "The existing .venv uses an incompatible Python version and will be rebuilt."
        Remove-Item -Recurse -Force $VenvPath
        $createVenv = $true
    }
}

if ($createVenv) {
    Write-Step "Creating the local virtual environment"
    Invoke-SystemPython -Python $Python -Arguments @("-m", "venv", $VenvPath)
}
else {
    Write-Step "Using the existing local virtual environment"
}

Write-Step "Installing Optimus and development checks"
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
$EditableSpec = "$ProjectRoot[dev]"
& $VenvPython -m pip install -e $EditableSpec
if ($LASTEXITCODE -ne 0) { throw "Optimus dependency installation failed." }

if (-not (Test-Path $EnvPath)) {
    Write-Step "Creating .env configuration"
    Copy-Item $EnvExamplePath $EnvPath
}

$currentKey = Get-DotEnvValue "OPENAI_API_KEY"
if ([string]::IsNullOrWhiteSpace($currentKey) -or $currentKey -eq "replace_me") {
    Write-Step "Configuring the OpenAI API key"
    Write-Host "Paste the API key from your OpenAI API project. Input is hidden."
    $newKey = Read-HiddenText "OPENAI_API_KEY"
    if ([string]::IsNullOrWhiteSpace($newKey)) {
        Write-Warning "No API key was entered. Optimus cannot perform web research until one is added to .env."
    }
    else {
        Set-DotEnvValue "OPENAI_API_KEY" ($newKey.Trim())
    }
}
else {
    Write-Step "Keeping the existing OpenAI API key"
}

$currentOwnerUsername = Get-DotEnvValue "OPTIMUS_OWNER_USERNAME"
if ([string]::IsNullOrWhiteSpace($currentOwnerUsername)) {
    Write-Step "Configuring the bootstrap owner username"
    $ownerUsername = Read-Host "OPTIMUS_OWNER_USERNAME"
    if ([string]::IsNullOrWhiteSpace($ownerUsername)) {
        throw "OPTIMUS_OWNER_USERNAME is required."
    }
    Set-DotEnvValue "OPTIMUS_OWNER_USERNAME" ($ownerUsername.Trim())
}

$currentOwnerPassword = Get-DotEnvValue "OPTIMUS_OWNER_PASSWORD"
if ([string]::IsNullOrWhiteSpace($currentOwnerPassword) -or $currentOwnerPassword -eq "replace_with_a_long_owner_password") {
    Write-Step "Configuring the bootstrap owner password"
    $ownerPassword = Read-HiddenText "OPTIMUS_OWNER_PASSWORD"
    if ([string]::IsNullOrWhiteSpace($ownerPassword)) {
        throw "OPTIMUS_OWNER_PASSWORD is required."
    }
    Set-DotEnvValue "OPTIMUS_OWNER_PASSWORD" ($ownerPassword.Trim())
}

Write-Step "Applying estimator reliability defaults"
Set-DotEnvDefault "OPENAI_FALLBACK_MODEL" "gpt-4.1-mini"
Set-DotEnvDefault "WEB_SEARCH_CONTEXT_SIZE" "medium"
Set-DotEnvDefault "ESTIMATOR_REASONING_EFFORT" "low"
Set-DotEnvDefault "OPENAI_TIMEOUT_SECONDS" "180"

Write-Step "Applying owner-control defaults"
Set-DotEnvValue "AUTONOMY_MODE" "owner_full_control"
Set-DotEnvValue "DIRECT_OWNER_CHAT_DEFAULT" "true"
Set-DotEnvValue "AGENT_DELEGATION_ENABLED" "true"
Set-DotEnvValue "MAX_AGENT_CONSULTATIONS" "2"
Set-DotEnvValue "ALLOW_PUBLIC_HTTPS_PARTS_LINKS" "true"

Write-Step "Validating the local configuration"
& $VenvPython (Join-Path $ProjectRoot "scripts\validate_runtime.py")
if ($LASTEXITCODE -ne 0) {
    throw "Configuration validation failed."
}

$currentKey = Get-DotEnvValue "OPENAI_API_KEY"
if (-not [string]::IsNullOrWhiteSpace($currentKey) -and $currentKey -ne "replace_me") {
    Write-Step "Testing the OpenAI API connection"
    & $VenvPython (Join-Path $ProjectRoot "scripts\check_openai.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Installation succeeded, but the OpenAI test failed. Run RESET_OPENAI_KEY.bat for a source-aware replacement and diagnostic."
    }
}

Write-Step "Windows setup complete"
Write-Host "Start Optimus by double-clicking local.bat" -ForegroundColor Green
exit 0
