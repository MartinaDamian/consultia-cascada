param([ValidateSet("vulnerable","hardened")][string]$Modo = "vulnerable")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

docker compose --profile tools -f docker-compose.yml -f docker-compose.hardened.yml down -v 2>$null | Out-Null

if ($Modo -eq "hardened") {
    docker compose --profile tools -f docker-compose.yml -f docker-compose.hardened.yml up -d --build
} else {
    docker compose --profile tools -f docker-compose.yml up -d --build
}

Write-Host "Modo '$Modo' listo. Gateway: http://localhost:8080/health"
