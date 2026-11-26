param([Parameter(Mandatory=$true)][ValidateSet("antes","despues")][string]$Label)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
# Parametros fijos para que antes/despues sean comparables
docker compose --profile tools exec tester python scenario.py --label $Label --baseline 10 --attack 40 --recovery 30 --workers 40
