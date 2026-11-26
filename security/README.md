# Bloque P4 — Zero Trust, mTLS y Rotación de Secretos

Carpeta destinada a los artefactos de seguridad de la Persona 4:

1. `gen_certs.sh` / `gen_certs.ps1`: script con `openssl` para crear la CA interna y certificados firmados con SAN para `gateway`, `api`, `llm`, `stt` y `db`.
2. `rotate_db_secret.sh` / `rotate_db_secret.ps1`: script de rotación de la contraseña de PostgreSQL (actualiza la clave en `db`, escribe el nuevo secreto montado en `DB_PASSWORD_FILE` y reinicia `api` verificando que la credencial anterior falla).
3. Políticas de mínimo privilegio (`user`, `read_only: true`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`) integradas en `docker-compose.hardened.yml`.

> Nota: `services/api/app.py` ya soporta lectura de contraseña desde archivo mediante la variable de entorno `DB_PASSWORD_FILE` (por ejemplo `/run/secrets/db_password`).
