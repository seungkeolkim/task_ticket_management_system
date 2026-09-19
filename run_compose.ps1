param([string]$Action)

$ErrorActionPreference = "Stop"
# PowerShell 7.3+ must also let us propagate native exit codes explicitly.
$PSNativeCommandUseErrorActionPreference = $false

if ($Action -cnotin @("start", "stop")) {
    [Console]::Error.WriteLine("Usage: .\run_compose.ps1 {start|stop}")
    exit 2
}

$previousPort = $env:APP_PORT
$previousConfig = $env:HOST_CONFIG_FILE
$locationPushed = $false
$runnerExitCode = 1

try {
    $configFile = $env:APP_CONFIG_FILE
    if ([string]::IsNullOrEmpty($configFile)) {
        $configFile = Join-Path $PSScriptRoot "config/application.toml"
    }
    # Resolve relative paths before changing directory; no wildcard expansion.
    $configFile = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($configFile)

    if ($Action -ceq "start") {
        $pythonCommand = $null
        $pythonArguments = @()
        $localPython = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
        $candidates = @($localPython, "python", "python3", "py")
        foreach ($candidate in $candidates) {
            $command = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($null -eq $command) { continue }
            $prefixArguments = @()
            if ($candidate -eq "py") { $prefixArguments = @("-3") }
            $ErrorActionPreference = "Continue"
            $null = & $command.Source @prefixArguments -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
            $probeExitCode = $LASTEXITCODE
            $ErrorActionPreference = "Stop"
            if ($probeExitCode -eq 0) {
                $pythonCommand = $command.Source
                $pythonArguments = $prefixArguments
                break
            }
        }
        if ($null -eq $pythonCommand) {
            throw "Python 3.11 or newer is required"
        }

        $portReader = Join-Path $PSScriptRoot "scripts/read-compose-port.py"
        $ErrorActionPreference = "Continue"
        $port = & $pythonCommand @pythonArguments $portReader $configFile
        $readerExitCode = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        if ($readerExitCode -ne 0) { exit $readerExitCode }
        $env:APP_PORT = [string]$port
        $composeArguments = @("compose", "-f", "compose.yaml", "up", "--build", "--detach")
    }
    else {
        # Down must work even if the config is missing or temporarily invalid.
        $env:APP_PORT = "8000"
        $composeArguments = @("compose", "-f", "compose.yaml", "down")
    }

    $env:HOST_CONFIG_FILE = $configFile
    Push-Location -LiteralPath $PSScriptRoot
    $locationPushed = $true
    $dockerCommand = Get-Command docker -ErrorAction Stop
    $ErrorActionPreference = "Continue"
    & $dockerCommand @composeArguments
    $runnerExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($null -eq $runnerExitCode) { $runnerExitCode = 1 }
}
catch {
    [Console]::Error.WriteLine("compose_runner_error: " + $_.Exception.Message)
    $runnerExitCode = 1
}
finally {
    if ($locationPushed) { Pop-Location }
    $env:APP_PORT = $previousPort
    $env:HOST_CONFIG_FILE = $previousConfig
}

exit $runnerExitCode
