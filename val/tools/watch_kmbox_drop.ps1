# Live monitor for the kmbox-net link.
#
# Pings the kmbox IP every second and tracks how many consecutive replies
# succeed before the link drops. When you collegate il mouse al kmbox the
# log will show the exact tick at which the dongle disappears, which is
# strong evidence of a brown-out (rather than a network / firmware issue).
#
# Run with:  powershell -File tools\watch_kmbox_drop.ps1
# Stop with: Ctrl+C
#
# Compatible with Windows PowerShell 5.1 and PowerShell 7+.

$ip = '192.168.2.188'
$consecutiveOk = 0
$lastState = 'unknown'

# Detect PS major version so we can pick the right Test-Connection
# parameter set. PS 5.1 uses -ComputerName; PS 7+ uses -TargetName plus
# -TimeoutSeconds. The semantics are equivalent, only the parameter
# names changed.
$psMajor = $PSVersionTable.PSVersion.Major

Write-Host "Pinging $ip every 1s. Plug/unplug the mouse and watch the log."
Write-Host "Detected PowerShell $($PSVersionTable.PSVersion). Press Ctrl+C to stop."
Write-Host ""

function Test-KmboxOnce {
    param([string]$Target, [int]$PsMajor)

    if ($PsMajor -ge 7) {
        # PowerShell 7+: -TargetName + -TimeoutSeconds + -Count
        return Test-Connection -TargetName $Target -Count 1 `
            -TimeoutSeconds 1 -ErrorAction SilentlyContinue
    } else {
        # Windows PowerShell 5.1: -ComputerName + -Count + -Quiet
        # ``-Quiet`` returns a bool instead of a PingReply object; combine
        # with ``Send`` from the .NET API for a per-ping latency measure.
        $ping = New-Object System.Net.NetworkInformation.Ping
        try {
            $reply = $ping.Send($Target, 1000)
            if ($reply.Status -eq 'Success') {
                # Wrap into a shape the caller code expects
                return [PSCustomObject]@{
                    Status = 'Success'
                    Latency = [int]$reply.RoundtripTime
                }
            }
            return $null
        } catch {
            return $null
        }
    }
}

while ($true) {
    $t = Get-Date -Format "HH:mm:ss"
    $reply = Test-KmboxOnce -Target $ip -PsMajor $psMajor

    if ($reply -and $reply.Status -eq 'Success') {
        $consecutiveOk++
        if ($lastState -ne 'up') {
            Write-Host "$t  LINK UP   (rtt=$($reply.Latency)ms)" -ForegroundColor Green
            $lastState = 'up'
            $consecutiveOk = 1
        } elseif ($consecutiveOk % 10 -eq 0) {
            Write-Host "$t  link up   (last rtt=$($reply.Latency)ms, $consecutiveOk consecutive OKs)"
        }
    } else {
        if ($lastState -ne 'down') {
            Write-Host "$t  LINK DOWN (after $consecutiveOk consecutive OKs)" -ForegroundColor Red
            $lastState = 'down'
            $consecutiveOk = 0
            # On link drop, also dump current USB Ethernet adapter state
            $adapters = Get-PnpDevice -Class Net | Where-Object {
                $_.FriendlyName -match 'ASIX|USB.*Ethernet'
            }
            foreach ($a in $adapters) {
                Write-Host ("           $($a.FriendlyName) -> $($a.Status) ($($a.ConfigManagerErrorCode))") -ForegroundColor Yellow
            }
        }
    }
    Start-Sleep -Seconds 1
}
