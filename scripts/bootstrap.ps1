# Run after cloning your own Agent Hub repository. No secret is passed in argv.
param(
    [Parameter(Mandatory=$true)][string]$Url,
    [string[]]$Map = @(),
    [string]$TokenFile,
    [string]$Project,
    [string[]]$Clients = @('codex', 'claude')
)
$ErrorActionPreference = 'Stop'
$AgentHubRepo = Split-Path -Parent $PSScriptRoot
$AgentHubVenvPython = Join-Path $AgentHubRepo '.venv\Scripts\python.exe'
if (-not (Test-Path $AgentHubVenvPython)) {
    py -3 -m venv (Join-Path $AgentHubRepo '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required; virtual environment creation failed.' }
}
& $AgentHubVenvPython -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
& $AgentHubVenvPython -m pip install -r (Join-Path $AgentHubRepo 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Agent Hub dependency installation failed.' }
& $AgentHubVenvPython -m pip install --no-deps -e $AgentHubRepo
if ($LASTEXITCODE -ne 0) { throw 'Agent Hub installation failed.' }
$AgentHubConfigureArgs = @('-m', 'agent_hub.cli', 'configure', '--url', $Url)
foreach ($Mapping in $Map) { $AgentHubConfigureArgs += @('--map', $Mapping) }
if ($TokenFile) { $AgentHubConfigureArgs += @('--token-file', $TokenFile) }
if ($Project) { $AgentHubConfigureArgs += @('--project', $Project) }
& $AgentHubVenvPython @AgentHubConfigureArgs
if ($LASTEXITCODE -ne 0) { throw 'Agent Hub configuration failed.' }
& $AgentHubVenvPython -m agent_hub.cli setup --clients @Clients
if ($LASTEXITCODE -ne 0) { throw 'Client setup failed.' }
& $AgentHubVenvPython -m agent_hub.cli doctor
if ($LASTEXITCODE -ne 0) { throw 'Doctor found a connection or credential problem.' }
Write-Output "Setup complete. Start capture with: & '$AgentHubVenvPython' -m agent_hub.cli watch"
