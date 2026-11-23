# Windows version of demo-up.sh: start the full Maru Vend + Maru Power demo on one PC (test environment only).
# Needs PHP 8.3 (extensions: pdo_mysql, pdo_sqlite, curl, mbstring) and MariaDB, both on PATH.
#
#   powershell -ExecutionPolicy Bypass -File scripts\demo-up.ps1 -DbPass yourpass -Reset
#   powershell -ExecutionPolicy Bypass -File scripts\demo-up.ps1 -Stop
param(
    [string]$DbPass = $env:MV_DB_PASS,
    [string]$DbRootPass = "",
    [int]$ApiPort = 8080,
    [int]$ChannelsPort = 8081,
    [int]$SimPort = 8099,
    [switch]$Reset,
    [switch]$Stop
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$pidFile = Join-Path $env:TEMP "maruvend-demo.pids"

function Stop-Demo {
    if (Test-Path $pidFile) {
        Get-Content $pidFile | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
        Remove-Item $pidFile
    }
}
Stop-Demo
if ($Stop) { Write-Host "Demo stopped."; exit 0 }
if (-not $DbPass) { throw "Give the database password: -DbPass yourpass" }

foreach ($tool in "php", "mariadb") {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not on PATH. Install it, or add its folder to PATH." }
}
$mods = (php -m) -join " "
foreach ($m in "pdo_mysql", "pdo_sqlite", "curl", "mbstring") {
    if ($mods -notmatch $m) { throw "PHP extension '$m' is off. Enable it in php.ini (extension=$m)." }
}

foreach ($port in $ApiPort, $ChannelsPort, $SimPort) {
    $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($busy) {
        $owner = (Get-Process -Id $busy[0].OwningProcess -ErrorAction SilentlyContinue).ProcessName
        throw "Port $port is already used by '$owner' (Docker or another server). Stop it, or pick other ports, e.g. -ApiPort 9080 -ChannelsPort 9081 -SimPort 9099"
    }
}

$env:MV_DB_PASS = $DbPass
$env:MV_CORE_URL = "http://127.0.0.1:$ApiPort"
$env:MV_DEMO = "1"

if ($Reset) {
    $rootArgs = @("-u", "root")
    if ($DbRootPass) { $rootArgs += "-p$DbRootPass" }
    $sql = "DROP DATABASE IF EXISTS maruvend; CREATE DATABASE maruvend; " +
           "CREATE USER IF NOT EXISTS 'maruvend'@'localhost' IDENTIFIED BY '$DbPass'; " +
           "CREATE USER IF NOT EXISTS 'maruvend'@'127.0.0.1' IDENTIFIED BY '$DbPass'; " +
           "GRANT ALL ON maruvend.* TO 'maruvend'@'localhost'; GRANT ALL ON maruvend.* TO 'maruvend'@'127.0.0.1';"
    & mariadb @rootArgs -e $sql
    if ($LASTEXITCODE) { throw "Could not set up the database. If root has a password, add -DbRootPass." }
    Remove-Item (Join-Path $env:TEMP "maruvend-sim.sqlite*") -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $env:TEMP "maruvend-anchors\anchors.jsonl") -ErrorAction SilentlyContinue
    php bin/mv migrate
    php bin/mv seed
    foreach ($kv in @("bpc_timeout_s 4", "worker_margin_s 2", "advice_first_delay_s 3", "advice_interval_s 2", "advice_window_s 20", "rate_per_s 5")) {
        php bin/mv setting:set @($kv -split " ") | Out-Null
    }
    $env:MV_NEW_PASSWORD = "bpc-demo-pass"; php bin/mv user:add bpc.viewer bpc_viewer
    $env:MV_NEW_PASSWORD = "admin1-pass"; php bin/mv user:add admin1 admin | Out-Null
    $env:MV_NEW_PASSWORD = "admin2-pass"; php bin/mv user:add admin2 admin | Out-Null
    $env:MV_NEW_PASSWORD = "maru1234"; php bin/mv portal:user demo@marupower.test "Lethabo Molefe"
    Remove-Item Env:MV_NEW_PASSWORD
}
php bin/mv setting:set bpc_endpoint "http://127.0.0.1:$SimPort" | Out-Null

$logs = Join-Path $env:TEMP "maruvend-logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$procs = @()
function Start-Bg([string]$name, [string[]]$phpArgs) {
    $p = Start-Process php -ArgumentList $phpArgs -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput "$logs\$name.log" -RedirectStandardError "$logs\$name.err.log"
    $script:procs += $p.Id
}
Start-Bg "sim"      @("-S", "127.0.0.1:$SimPort", "simulator/index.php")
Start-Bg "api"      @("-S", "127.0.0.1:$ApiPort", "-t", "public", "public/index.php")
Start-Bg "channels" @("-S", "127.0.0.1:$ChannelsPort", "-t", "channels/public", "channels/public/index.php")
foreach ($w in 1..2) { Start-Bg "worker$w" @("bin/mv", "worker", "--id=w$w") }
Start-Bg "sms" @("bin/mv", "sms")
$procs | Set-Content $pidFile
Start-Sleep 2

Write-Host @"

Maru Power      http://127.0.0.1:$ApiPort/power   (customer portal: demo@marupower.test / maru1234)
Merchant POS    http://127.0.0.1:$ChannelsPort/pos     (operator till1, PIN 1234)
Web store       http://127.0.0.1:$ChannelsPort/
USSD emulator   http://127.0.0.1:$ChannelsPort/ussd-phone
BPC dashboard   http://127.0.0.1:$ApiPort/bpc
BPC simulator   http://127.0.0.1:$SimPort
Logs            $logs
Stop with:      powershell -ExecutionPolicy Bypass -File scripts\demo-up.ps1 -Stop

Test meters: 94949494949 (Mpho Domestic), 04040404040 (Kgosi Business Centre), 01234567890 (Naledi Clinic)
"@
Start-Process "http://127.0.0.1:$ChannelsPort/pos"
Start-Process "http://127.0.0.1:$ApiPort/power"
