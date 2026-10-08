# Stocking 서버 실행
#   .\run.ps1          이 PC 에서만 (http://127.0.0.1:8800)
#   .\run.ps1 -Lan     집 와이파이의 노트북·폰에서도 접속 (다른 기기는 .env 의 APP_PASSWORD 필요)
param([switch]$Lan)

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$bind = "127.0.0.1"
if ($Lan) {
    $envFile = Join-Path $PSScriptRoot ".env"
    $hasPw = (Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^\s*APP_PASSWORD\s*=\s*\S+' -Quiet)
    if (-not $hasPw) {
        Write-Host "집 와이파이로 열려면 먼저 .env 에 APP_PASSWORD=비밀번호 를 넣어주세요." -ForegroundColor Yellow
        exit 1
    }
    $bind = "0.0.0.0"
    $ips = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -ExpandProperty IPAddress
    Write-Host "이 PC:        http://127.0.0.1:8800"
    foreach ($ip in $ips) { Write-Host "노트북·폰:    http://${ip}:8800  (아이디는 아무거나, 비밀번호 = APP_PASSWORD)" }
}
& $py -m uvicorn backend.main:app --host $bind --port 8800 --app-dir $PSScriptRoot
