# P4 — Zero Trust, mTLS y rotación de secretos

## Componentes

- `generate_certs.ps1` genera una CA local y certificados con SAN para `gateway`, `api`, `llm`, `stt`, `db` y `tester`. El directorio `security/certs/` está excluido de Git. El script reemplaza ese directorio al ejecutarse: úsalo solo para una instalación nueva o cuando quieras renovar todos los certificados.
- Nginx usa su certificado cliente para conectarse al API por HTTPS y verifica el certificado del servidor. Gunicorn en el API requiere certificado cliente firmado por la CA.
- El API llama a `stt` y `llm` por HTTPS, verifica la CA y presenta su certificado cliente. También valida el certificado de PostgreSQL con `DB_SSLMODE=verify-full`.
- `db_net` es una red interna compartida únicamente por `api` y `db`. El secreto local `security/secrets/db_password.txt` se excluye de Git y se monta como Docker Secret en `/run/secrets/db_password`.
- `rotate_secret.ps1` cambia la contraseña de PostgreSQL, actualiza el archivo secreto, recrea el API y verifica que la credencial antigua ya no funciona.

## Preparación y despliegue

Desde Windows PowerShell, en la raíz del repositorio:

```powershell
.\security\generate_certs.ps1
New-Item -ItemType Directory -Force security\secrets | Out-Null
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$bytes = New-Object byte[] 32
$rng.GetBytes($bytes)
[System.IO.File]::WriteAllText("security/secrets/db_password.txt", [Convert]::ToBase64String($bytes))

docker compose -f docker-compose.yml -f docker-compose.hardened.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.hardened.yml up -d --build
```

La creación inicial del secreto debe hacerse antes del primer arranque endurecido. Si PostgreSQL ya tiene un volumen inicializado con otra contraseña, rota las credenciales con el script de rotación o elimina el volumen solo cuando sea seguro perder sus datos.

## Verificación

```powershell
curl.exe -i http://localhost:8080/health
curl.exe -i http://localhost:8080/citas
curl.exe -i http://localhost:8080/consulta

# Debe fallar con alerta TLS porque no se presenta certificado cliente.
docker compose -f docker-compose.yml -f docker-compose.hardened.yml exec api python -c "import requests; requests.get('https://api:5000/health', verify='/certs/ca.crt')"
# Debe imprimir 200 con un certificado de cliente válido.
docker compose -f docker-compose.yml -f docker-compose.hardened.yml exec api python -c "import requests; r=requests.get('https://api:5000/health', verify='/certs/ca.crt', cert=('/certs/api.crt','/certs/api.key')); print(r.status_code)"

docker compose --profile tools -f docker-compose.yml -f docker-compose.hardened.yml up -d tester
$targets = foreach ($service in @("api", "llm", "stt", "db")) {
    $id = docker compose -f docker-compose.yml -f docker-compose.hardened.yml ps -q $service
    $container = docker inspect $id | ConvertFrom-Json
    $suffix = if ($service -eq "db") { "*_db_net" } else { "*_backend" }
    $network = $container.NetworkSettings.Networks.PSObject.Properties |
        Where-Object { $_.Name -like $suffix -and $_.Value.Aliases -contains $service } |
        Select-Object -First 1
    $network.Value.IPAddress
}
docker compose --profile tools -f docker-compose.yml -f docker-compose.hardened.yml exec tester nmap -Pn -n --max-retries 1 -p 5000,5001,5002,5432 $targets
docker inspect consultia-cascada-api-1 consultia-cascada-db-1 --format '{{range .Config.Env}}{{println .}}{{end}}'
```

`tester` solo pertenece a `frontend`; al escanear las IPs internas de API, STT, LLM y PostgreSQL, sus puertos deben aparecer como `filtered`. La inspección de contenedores debe mostrar `DB_PASSWORD=` vacío y `DB_PASSWORD_FILE=/run/secrets/db_password`, nunca el valor de la contraseña.

## Rotación en caliente

Con el stack endurecido en ejecución:

```powershell
.\security\rotate_secret.ps1
```

El resultado se registra en `evidencias/P4_rotacion_secreto.txt`. Al terminar el laboratorio:

```powershell
docker compose --profile tools -f docker-compose.yml -f docker-compose.hardened.yml down -v
```

`down -v` elimina también los volúmenes de PostgreSQL.
