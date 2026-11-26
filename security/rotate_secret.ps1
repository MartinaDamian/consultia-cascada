# security/rotate_secret.ps1
# Rotacion en caliente de la contrasena de PostgreSQL sin caida del servicio.
$ErrorActionPreference = "Stop"

$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

$SecretFile = Join-Path $PSScriptRoot "secrets\db_password.txt"
$EvidenceDir = Join-Path $Root "evidencias"
$EvidenceFile = Join-Path $EvidenceDir "P4_rotacion_secreto.txt"
if (-not (Test-Path $EvidenceDir)) {
    New-Item -ItemType Directory -Path $EvidenceDir | Out-Null
}

if (-not (Test-Path $SecretFile)) {
    throw "No se encontro el archivo de secreto actual: $SecretFile"
}
$OldPassword = [System.IO.File]::ReadAllText($SecretFile).Trim()

# 1. Generar nueva contrasena aleatoria segura (24 caracteres, sin comillas ni backslash)
$Chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#%_-".ToCharArray()
$Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$Bytes = New-Object byte[] 24
$Rng.GetBytes($Bytes)
$NewPassword = -join ($Bytes | ForEach-Object { $Chars[$_ % $Chars.Length] })

$Log = New-Object System.Collections.Generic.List[string]
function Add-Log([string]$Line) {
    Write-Host $Line
    $Log.Add($Line)
}

function Invoke-Docker([string[]]$DockerArgs) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & docker @DockerArgs 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return @{ Output = ($out -join "`n"); ExitCode = $code }
}

Add-Log "=== P4: Rotacion en caliente de secreto PostgreSQL ==="
Add-Log ("Fecha: {0}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"))

# 2. Actualizar contrasena en PostgreSQL activo
Add-Log "[1/5] Ejecutando ALTER USER consultia en el contenedor db..."
$res = Invoke-Docker @("compose", "-f", "docker-compose.yml", "-f", "docker-compose.hardened.yml", "exec", "-T", "db", "psql", "-U", "consultia", "-d", "consultia", "-c", "ALTER USER consultia WITH PASSWORD '$NewPassword';")
if ($res.ExitCode -ne 0) {
    throw "Error al ejecutar ALTER USER en db: $($res.Output)"
}
Add-Log $res.Output

# 3. Actualizar archivo de secreto sin saltos de linea ni BOM
Add-Log "[2/5] Actualizando security/secrets/db_password.txt (sin saltos de linea)..."
[System.IO.File]::WriteAllText($SecretFile, $NewPassword, [System.Text.UTF8Encoding]::new($false))
$WrittenLen = ([System.IO.File]::ReadAllBytes($SecretFile)).Length
Add-Log "Archivo actualizado ($WrittenLen bytes)."

# 4. Recrear unicamente el servicio api para montar el nuevo secreto
Add-Log "[3/5] Recreando unicamente el servicio api..."
$res = Invoke-Docker @("compose", "-f", "docker-compose.yml", "-f", "docker-compose.hardened.yml", "up", "-d", "--no-deps", "--force-recreate", "api")
if ($res.ExitCode -ne 0) {
    throw "Error al recrear api: $($res.Output)"
}
Add-Log $res.Output

# 5. Verificar /citas HTTP 200 con la nueva credencial
Add-Log "[4/5] Verificando http://localhost:8080/citas con la nueva contrasena..."
$Status = 0
$Body = ""
for ($i = 1; $i -le 15; $i++) {
    try {
        $Resp = Invoke-WebRequest -Uri "http://localhost:8080/citas" -UseBasicParsing -TimeoutSec 5
        $Status = $Resp.StatusCode
        $Body = $Resp.Content.Trim()
        if ($Status -eq 200) { break }
    } catch {
        Start-Sleep -Seconds 1
    }
}
if ($Status -ne 200) {
    throw "Error: /citas no devolvio HTTP 200 tras rotar el secreto (ultimo estado: $Status)."
}
Add-Log "GET /citas -> HTTP $Status"
Add-Log "Respuesta: $Body"

# 6. Verificar que la clave anterior ya no autentica en PostgreSQL (via red db_net con scram-sha-256 + SSL)
Add-Log "[5/5] Verificando rechazo de la clave anterior en PostgreSQL..."
$res = Invoke-Docker @("compose", "-f", "docker-compose.yml", "-f", "docker-compose.hardened.yml", "exec", "-T", "-e", "PGPASSWORD=$OldPassword", "-e", "PGSSLMODE=require", "db", "psql", "-h", "db", "-U", "consultia", "-d", "consultia", "-c", "SELECT 1;")
if ($res.ExitCode -eq 0) {
    throw "FALLO DE SEGURIDAD: la contrasena anterior todavia autentica en PostgreSQL."
}
Add-Log "Autenticacion con clave anterior rechazada (exit code $($res.ExitCode)):"
Add-Log $res.Output

Add-Log "=== Rotacion completada correctamente ==="
[System.IO.File]::WriteAllLines($EvidenceFile, $Log, [System.Text.UTF8Encoding]::new($false))
Write-Host "Evidencia guardada en: $EvidenceFile" -ForegroundColor Green
exit 0
