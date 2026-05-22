# Live monitor for USB Ethernet adapters and IPv4 addresses.
# Run with:  powershell -File tools\watch_usb.ps1
# Stop with: Ctrl+C
#
# Useful while diagnosing dongle / power / cable issues — refreshes
# every 2 seconds so a freshly-enumerated dongle becomes visible
# the moment Windows finishes registering it.

while ($true) {
    Clear-Host
    Write-Host ("=== {0} ===" -f (Get-Date -Format "HH:mm:ss"))
    Write-Host ""
    Write-Host "USB Ethernet adapters:"
    Get-PnpDevice -Class Net |
        Where-Object { $_.FriendlyName -match "ASIX|USB.*Ethernet|RTL.*USB|Realtek USB" } |
        Select-Object FriendlyName, Status, ConfigManagerErrorCode |
        Format-Table -AutoSize

    Write-Host "Live IPv4 addresses (excluding loopback / link-local):"
    Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object InterfaceAlias, IPAddress, PrefixLength |
        Format-Table -AutoSize

    Write-Host "Press Ctrl+C to stop. Refresh in 2s..."
    Start-Sleep -Seconds 2
}
