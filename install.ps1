# Slim11 Builder installer for Windows.
#
#   irm https://github.com/NermalYT/slim11-builder/releases/latest/download/install.ps1 | iex
#
# Or download it and run:  powershell -ExecutionPolicy Bypass -File install.ps1 [-Ai on|off] [-Register] [-Yes]
param(
    [ValidateSet("", "on", "off")] [string]$Ai = "",
    [switch]$Register,
    [string]$Version = "",
    [string]$Dir = "$env:LOCALAPPDATA\Slim11",
    [switch]$Yes
)
$ErrorActionPreference = "Stop"
$Repo = if ($env:SLIM11_REPO) { $env:SLIM11_REPO } else { "NermalYT/slim11-builder" }

function Ask([string]$Question, [bool]$Default) {
    if ($Yes) { return $Default }
    $hint = if ($Default) { "[Y/n]" } else { "[y/N]" }
    $answer = Read-Host "$Question $hint"
    if ($answer -match '^[Yy]') { return $true }
    if ($answer -match '^[Nn]') { return $false }
    return $Default
}

$py = $null
foreach ($candidate in @(@("py", "-3"), @("python"))) {
    $exe = Get-Command $candidate[0] -ErrorAction SilentlyContinue
    if (-not $exe) { continue }
    $args_ = @($candidate | Select-Object -Skip 1) + @("-c", "import sys; sys.exit(sys.version_info < (3, 10))")
    & $exe.Source @args_ 2>$null
    if ($LASTEXITCODE -eq 0) { $py = @($exe.Source) + @($candidate | Select-Object -Skip 1); break }
}
if (-not $py) { throw "Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ (tick 'Add to PATH')." }

if ($env:SLIM11_WHEEL) { $wheel = $env:SLIM11_WHEEL } else {
$api = if ($Version) { "https://api.github.com/repos/$Repo/releases/tags/$Version" } else { "https://api.github.com/repos/$Repo/releases/latest" }
Write-Host "Finding the Slim11 release..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$release = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "slim11-installer" }
$wheel = ($release.assets | Where-Object { $_.name -like "*.whl" } | Select-Object -First 1).browser_download_url
if (-not $wheel) { throw "Release $($release.tag_name) has no wheel." }
}

Write-Host "Installing into $Dir"
$pyExe = $py[0]; $pyArgs = @($py | Select-Object -Skip 1)
& $pyExe @pyArgs -m venv "$Dir\venv"
if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
$venvPy = "$Dir\venv\Scripts\python.exe"
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet --upgrade $wheel
if ($LASTEXITCODE -ne 0) { throw "pip could not install $wheel" }
$slim11 = "$Dir\venv\Scripts\slim11.exe"

Write-Host ""
Write-Host "AI agent features let AI coding tools (Claude Code, Codex, Antigravity, Gemini CLI, ...)"
Write-Host "control Slim11 through MCP: read your ISO, change what gets removed, preview and run builds."
if (-not $Ai) { $Ai = if (Ask "Turn on AI agent features?" $false) { "on" } else { "off" } }
& $slim11 ai $Ai | Out-Null
Write-Host "AI features: $Ai (change any time with 'slim11 ai on' / 'slim11 ai off' or in the app)"
if ($Ai -eq "on") {
    $tools = (& $venvPy -c "from slim11.ai import detected_tools; print(' '.join(detected_tools()))").Trim()
    if ($tools) {
        # Editing another tool's config needs a yes: -Register, or answering the question.
        if ($Register -or (-not $Yes -and (Ask "Add Slim11 to these AI tools: $tools?" $true))) {
            & $slim11 ai on --register detected 2>&1 | Where-Object { "$_" -match '^(Claude Code|Codex|Gemini CLI|claude|codex|gemini)' }
        } else {
            Write-Host "Not added to $tools. Run 'slim11 ai on --register detected' later, or 'slim11 ai' for manual setup."
        }
    } else {
        Write-Host "No AI tools detected. Run 'slim11 ai' to see how to connect one."
    }
}

$toolsDir = "$env:USERPROFILE\.slim11\tools"
if (-not (Get-ChildItem -Path $toolsDir -Recurse -Filter wimlib-imagex.exe -ErrorAction SilentlyContinue) -and
    -not (Get-Command wimlib-imagex -ErrorAction SilentlyContinue)) {
    Write-Host ""
    if (Ask "Builds need wimlib. Download wimlib 1.14.4 from wimlib.net into $toolsDir?" $true) {
        try {
            New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
            $zip = Join-Path $env:TEMP "wimlib.zip"
            Invoke-WebRequest "https://wimlib.net/downloads/wimlib-1.14.4-windows-x86_64-bin.zip" -OutFile $zip -TimeoutSec 60
            Expand-Archive $zip -DestinationPath $toolsDir -Force
            Remove-Item $zip
            Write-Host "wimlib installed."
        } catch {
            Write-Warning "Could not download wimlib ($_). Get it from https://wimlib.net/downloads/ and extract it into $toolsDir"
        }
    } else {
        Write-Host "Get wimlib from https://wimlib.net/downloads/ and extract it into $toolsDir"
    }
}

$scripts = "$Dir\venv\Scripts"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($userPath -split ';') -notcontains $scripts) {
    if (Ask "Add Slim11 to your PATH so you can run 'slim11' from any terminal?" $true) {
        [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(';') + ";" + $scripts), "User")
        Write-Host "Added. Open a new terminal to use it."
    }
}
Write-Host ""
Write-Host "Done. Run: slim11   (or $slim11)"
