param(
    [ValidateSet('baseline', 'all')][string]$Phase = 'all',
    [ValidateRange(1, 20)][int]$Repeats = 10,
    [ValidateRange(0, 20)][int]$PlainRepeats = 6
)
$ErrorActionPreference = 'Stop'
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCommand) {
    $dockerExe = $dockerCommand.Source
} else {
    $dockerExe = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (!$dockerExe) { throw 'Docker CLI not found. Install/start Docker Desktop.' }
}
$image = 'ghcr.io/userver-framework/ubuntu-22.04-userver@sha256:fca9c8ac7e97b4e2b042d822facbb152aec10a9d4e09c0862e44c50640f3f303'
& $dockerExe info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop in Linux container mode first.' }
$engineArch = & $dockerExe info --format '{{.Architecture}}'
if ($engineArch -notin @('amd64', 'x86_64')) { throw 'Use an x86-64 Docker host. ARM emulation distorts timing.' }
$studyRunKey = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 6)
$studyContainer = 'userver-study-' + $studyRunKey
$results = Join-Path $PSScriptRoot ('results\' + $studyRunKey)
New-Item -ItemType Directory -Path $results -Force | Out-Null
$hostInfo = [ordered]@{
    recorded_at = (Get-Date -Format o)
    os = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
    processor = (Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors)
    memory_bytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
    docker = (& $dockerExe info --format 'Engine={{.ServerVersion}} OS={{.OperatingSystem}} Kernel={{.KernelVersion}} Arch={{.Architecture}} CPUs={{.NCPU}} Memory={{.MemTotal}}')
    image = $image
}
$hostInfo | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $results 'host.json') -Encoding utf8
$containerId = & $dockerExe run --detach --name $studyContainer --cpus=4 --cpuset-cpus=0-3 --memory=8g --memory-swap=8g `
    --mount "type=bind,source=$PSScriptRoot,target=/study,readonly" `
    --mount "type=bind,source=$results,target=/results" `
    --mount 'type=volume,target=/workspace' `
    --workdir /workspace $image bash /study/scripts/experiment.sh $Phase $Repeats $PlainRepeats
if ($LASTEXITCODE -ne 0) { throw "Experiment failed. Logs: $results" }
$studyContainer | Set-Content -LiteralPath (Join-Path $results 'container.txt') -Encoding utf8
& $dockerExe logs --follow $studyContainer
if ($LASTEXITCODE -ne 0) { throw "Log connection interrupted. Container: $studyContainer; results: $results" }
$studyExitCode = & $dockerExe wait $studyContainer
if ($LASTEXITCODE -ne 0 -or $studyExitCode -ne '0') { throw "Experiment failed. Container: $studyContainer; logs: $results" }
$studyExitCode | Set-Content -LiteralPath (Join-Path $results 'exit-code.txt') -Encoding utf8
Write-Host "Results: $results"
Write-Host "Container and Linux volume retained: $studyContainer"
