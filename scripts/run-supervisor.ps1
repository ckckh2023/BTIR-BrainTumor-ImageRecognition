[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Leaf })]
    [string]$PythonExe,

    [int]$ApiPort = 8000,
    [ValidateRange(1, 300)]
    [int]$RestartDelaySeconds = 10,
    [ValidateRange(5, 300)]
    [int]$HealthCheckSeconds = 15,
    [ValidateRange(1, 300)]
    [int]$WorkerStartupGraceSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDirectory = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Write-SupervisorLog([string]$Message) {
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "$timestamp [supervisor] $Message" | Tee-Object -FilePath (Join-Path $logDirectory 'supervisor.log') -Append
}

function Start-ManagedProcess([string]$Name, [string[]]$Arguments) {
    Write-SupervisorLog "starting $Name"
    return Start-Process `
        -FilePath $PythonExe `
        -ArgumentList $Arguments `
        -WorkingDirectory $projectRoot `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDirectory "$Name.stdout.log") `
        -RedirectStandardError (Join-Path $logDirectory "$Name.stderr.log")
}

function Stop-ManagedProcess($Process, [string]$Name) {
    if ($null -ne $Process -and -not $Process.HasExited) {
        Write-SupervisorLog "stopping $Name (pid=$($Process.Id))"
        Stop-Process -Id $Process.Id -Force
        $Process.WaitForExit()
    }
}

function Get-HttpStatusCode([string]$Uri) {
    try {
        return [int](Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 3).StatusCode
    } catch {
        if ($null -ne $_.Exception.Response) {
            return [int]$_.Exception.Response.StatusCode
        }
        return $null
    }
}

function Get-ReadinessState([string]$Uri) {
    $response = $null
    try {
        $request = [System.Net.WebRequest]::Create($Uri)
        $request.Timeout = 3000
        $response = $request.GetResponse()
    } catch [System.Net.WebException] {
        $response = $_.Exception.Response
    }

    if ($null -eq $response) {
        return $null
    }

    try {
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        $content = $reader.ReadToEnd()
        $payload = $content | ConvertFrom-Json
        $components = if ($null -ne $payload.detail) {
            $payload.detail.components
        } else {
            $payload.components
        }
        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Components = $components
        }
    } finally {
        $response.Close()
    }
}

function Get-JsonResponse([string]$Uri) {
    try {
        return (Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 3).Content | ConvertFrom-Json
    } catch {
        return $null
    }
}

$apiArguments = @('-m', 'uvicorn', 'api.app:app', '--host', '127.0.0.1', '--port', $ApiPort)
$workerArguments = @('-m', 'workers.run_worker')
$api = $null
$worker = $null
$workerStartedAt = [datetime]::MinValue
$apiHealthFailures = 0
$nextHealthCheck = [datetime]::MinValue

try {
    $api = Start-ManagedProcess 'api' $apiArguments
    $worker = Start-ManagedProcess 'worker' $workerArguments
    $workerStartedAt = Get-Date

    while ($true) {
        if ($api.HasExited) {
            Write-SupervisorLog "api exited with code $($api.ExitCode); restarting in $RestartDelaySeconds seconds"
            Start-Sleep -Seconds $RestartDelaySeconds
            $api = Start-ManagedProcess 'api' $apiArguments
            $apiHealthFailures = 0
        }

        if ($worker.HasExited) {
            Write-SupervisorLog "worker exited with code $($worker.ExitCode); restarting in $RestartDelaySeconds seconds"
            Start-Sleep -Seconds $RestartDelaySeconds
            $worker = Start-ManagedProcess 'worker' $workerArguments
            $workerStartedAt = Get-Date
        }

        if ((Get-Date) -ge $nextHealthCheck) {
            $nextHealthCheck = (Get-Date).AddSeconds($HealthCheckSeconds)
            $healthStatus = Get-HttpStatusCode "http://127.0.0.1:$ApiPort/healthz"
            if ($healthStatus -eq 200) {
                $apiHealthFailures = 0
            } else {
                $apiHealthFailures += 1
                Write-SupervisorLog "api health check failed (status=$healthStatus, failures=$apiHealthFailures)"
                if ($apiHealthFailures -ge 3) {
                    Stop-ManagedProcess $api 'api'
                    Start-Sleep -Seconds $RestartDelaySeconds
                    $api = Start-ManagedProcess 'api' $apiArguments
                    $apiHealthFailures = 0
                }
            }

            $readiness = Get-ReadinessState "http://127.0.0.1:$ApiPort/readyz"
            $queueState = Get-JsonResponse "http://127.0.0.1:$ApiPort/ops/queue"
            if (
                $null -ne $readiness -and
                $readiness.StatusCode -eq 503 -and
                $readiness.Components.redis -eq 'ok' -and
                $readiness.Components.inference_worker -eq 'unavailable' -and
                $null -ne $queueState -and
                $queueState.running_jobs -eq 0 -and
                ((Get-Date) - $workerStartedAt).TotalSeconds -ge $WorkerStartupGraceSeconds
            ) {
                Write-SupervisorLog 'worker is not registered; restarting worker after startup grace period'
                Stop-ManagedProcess $worker 'worker'
                Start-Sleep -Seconds $RestartDelaySeconds
                $worker = Start-ManagedProcess 'worker' $workerArguments
                $workerStartedAt = Get-Date
            }
        }

        Start-Sleep -Seconds 1
    }
} finally {
    Stop-ManagedProcess $worker 'worker'
    Stop-ManagedProcess $api 'api'
}
