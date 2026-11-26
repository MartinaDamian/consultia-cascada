# Bitácora de Uso de IA — Bloque P4 (Zero Trust, mTLS, Segmentación y Secretos)

**Responsable:** Mateo Cueva (P4)  
**Rama de trabajo:** `feat/zerotrust` (integrada en `main`)  
**Fecha:** 26/11/2026  

---

## 1. Resumen de Implementación P4
- **PKI interna y mTLS extremo a extremo:** Generación de CA raíz (`Consultia-Root-CA`, 4096 bits) y certificados firmados con SAN y EKU (`serverAuth`, `clientAuth`) para `gateway`, `api`, `llm`, `stt`, `db` y `tester`. Autenticación mutua obligatoria (`--cert-reqs 2` en Gunicorn, `proxy_ssl_verify on` en Nginx y `sslmode=verify-full` en PostgreSQL).
- **Segmentación estricta de red:** Creación de la red interna aislada `db_net` (`internal: true`) compartida exclusivamente entre `api` y `db`, bloqueando el acceso directo hacia PostgreSQL desde `gateway`, `llm`, `stt` y la red `frontend`.
- **Gestión y rotación de secretos en caliente:** Migración de credenciales en claro hacia Docker Secrets (`/run/secrets/db_password`), vaciando `DB_PASSWORD` y `POSTGRES_PASSWORD` en el entorno de los contenedores, e implementación de `security/rotate_secret.ps1` para rotación sin caída del servicio.

---

## 2. Registro de Interacciones con IA y Verificación Técnica

### Interacción 1: Automatización de PKI con OpenSSL en Docker sobre Windows
- **Herramienta:** Gemini / Antigravity
- **Objetivo / Prompt resumido:** Crear un script PowerShell (`security/generate_certs.ps1`) que utilice una imagen efímera `alpine/openssl` para emitir la CA raíz y los certificados con SAN de todos los microservicios sin depender de OpenSSL instalado localmente en Windows.
- **Fallo o limitación detectada en la salida inicial:** Al ejecutar el contenedor `alpine/openssl` pasando `sh -c "..."` como comando, OpenSSL devolvió `Invalid command 'sh'`, debido a que la imagen oficial define `openssl` como su `ENTRYPOINT` por defecto.
- **Fuente de verificación y corrección aplicada:** Se inspeccionó la configuración de la imagen Docker (`docker image inspect alpine/openssl`) y se añadió explícitamente `--entrypoint sh` junto con comprobación de `$LASTEXITCODE` en `security/generate_certs.ps1`, validando luego las cadenas X.509 y extensiones SAN con `openssl x509 -text`.

### Interacción 2: Permisos de llave privada SSL de PostgreSQL en volúmenes bind de Windows
- **Herramienta:** Gemini / Antigravity
- **Objetivo / Prompt resumido:** Configurar el servicio `db` (PostgreSQL) en `docker-compose.hardened.yml` con `-c ssl=on` montando `db.crt`, `db.key` y `ca.crt` desde `./security/certs/`.
- **Fallo o limitación detectada en la salida inicial:** Al levantar el contenedor en Windows, PostgreSQL abortó el arranque con `FATAL: could not load private key file "/var/lib/postgresql/certs/db.key": Permission denied` por permisos abiertos en montajes NTFS.
- **Fuente de verificación y corrección aplicada:** Se contrastó con la documentación oficial de PostgreSQL (*Secure TCP/IP Connections with SSL*), que exige que la clave privada sea propiedad del usuario del daemon (`postgres`, UID 70) y tenga permisos `0600`. Se ajustó el `entrypoint` de `db` en `docker-compose.hardened.yml` para copiar los certificados a `/tmp/pgcerts/`, aplicar `chown postgres:postgres` y `chmod 600 db.key` antes de invocar `docker-entrypoint.sh`.

### Interacción 3: Integración de controles Zero Trust (P4) con resiliencia (P3)
- **Herramienta:** GitHub Copilot (Agent Mode)
- **Objetivo / Prompt resumido:** Fusionar `feat/zerotrust` con los cambios de `main` (PR de P3: `resilience.py`, `pybreaker`, `limit_req`/`limit_conn` en Nginx) preservando tanto los códigos `429`/`503` con degradación parcial como el cifrado mTLS, la red `db_net` y los secretos.
- **Fallo o limitación detectada en la salida inicial:** En una primera prueba tras recrear `api`, una petición inmediata a `/consulta` agotó el límite estricto de `LLM_TIMEOUT` al sumarse la latencia simulada de `llm` con el handshake TLS inicial, disparando la degradación controlada (`503`).
- **Fuente de verificación y corrección aplicada:** Se verificó el comportamiento esperado en `services/api/resilience.py` y se reejecutaron las pruebas funcionales (`/health`, `/citas`, `/consulta` en `200 OK`, ráfaga `429` con `Retry-After: 2`, rechazo mTLS sin certificado, `nmap` desde `tester` e inspección de `docker inspect`), confirmando la convivencia completa entre P3 y P4.

---

## 3. Evidencias Generadas en `evidencias/`
- `evidencias/P4_mtls_prueba.txt` y `evidencias/P4_mtls_rechazo.png` — Prueba negativa (rechazo TLS sin certificado cliente) y positiva (`200 OK` con certificado `tester`) contra `https://api:5000/citas`.
- `evidencias/P4_segmentacion_nmap.txt` y `evidencias/P4_segmentacion_nmap.png` — Escaneo desde `tester` (`frontend`) demostrando el aislamiento de `api`, `llm`, `stt` y `db`.
- `evidencias/P4_secretos_inspect.txt` y `evidencias/P4_secretos_inspect.png` — Salida de `docker inspect` en `api` y `db` verificando ausencia de contraseñas en variables de entorno.
- `evidencias/P4_rotacion_secreto.txt` y `evidencias/P4_rotacion_secreto.png` — Ejecución de `security/rotate_secret.ps1`, recreación aislada de `api` y rechazo de la credencial anterior en PostgreSQL.
