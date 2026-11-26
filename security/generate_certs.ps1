# security/generate_certs.ps1
# Genera la CA raiz y certificados TLS/mTLS con SAN para los servicios de Consultia
$ErrorActionPreference = "Stop"

$CertDir = Join-Path $PSScriptRoot "certs"
if (Test-Path $CertDir) {
    Remove-Item -Recurse -Force $CertDir
}
New-Item -ItemType Directory -Path $CertDir | Out-Null

$shScript = @'
set -e
cd /certs

# 1. Crear CA Raiz
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 365 \
  -subj "/C=ES/O=ConsultiaLab/CN=Consultia-Root-CA" \
  -out ca.crt

# Funcion para emitir certificados firmados con SAN
issue_cert() {
  SERVICE=$1
  openssl genrsa -out "${SERVICE}.key" 2048
  openssl req -new -key "${SERVICE}.key" \
    -subj "/C=ES/O=ConsultiaLab/CN=${SERVICE}" \
    -out "${SERVICE}.csr"

  cat > "${SERVICE}.ext" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${SERVICE}
DNS.2 = localhost
IP.1 = 127.0.0.1
EOF

  openssl x509 -req -in "${SERVICE}.csr" -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out "${SERVICE}.crt" -days 365 -sha256 \
    -extfile "${SERVICE}.ext"

  rm -f "${SERVICE}.csr" "${SERVICE}.ext"
}

# 2. Emitir certificados para todos los servicios y cliente tester
for svc in gateway api llm stt db tester; do
  issue_cert "$svc"
done

chmod 644 *.crt
chmod 600 *.key
'@

$shScriptLF = $shScript -replace "`r`n", "`n"

Write-Host "Generando CA y certificados mTLS mediante Docker (alpine/openssl)..." -ForegroundColor Cyan
docker run --rm --entrypoint sh -v "${CertDir}:/certs" alpine/openssl -c $shScriptLF
if ($LASTEXITCODE -ne 0) {
    throw "Error al ejecutar OpenSSL en Docker."
}

Write-Host "Certificados generados exitosamente en: $CertDir" -ForegroundColor Green
Get-ChildItem $CertDir | Format-Table Name, Length, LastWriteTime