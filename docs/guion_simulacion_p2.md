# Guión y Manual de Simulación en Vivo — Persona 2
**Expositora:** Sara Chiriboga  
**Rol:** Persona 2 — Simulación del fallo y métricas  
**Tiempo estimado de intervención:** 2:30 a 3:00 minutos  
**Proyecto:** Consultia — Laboratorio de Fallos en Cascada (Sistemas Distribuidos - UDLA)

---

## 🖥️ 1. Preparación previa a la exposición (Setup de Pantalla)

Para lograr el mayor impacto visual y técnico ante el profesor, organiza tu pantalla en **3 terminales visibles** (o pestañas divididas de Windows Terminal):

1. **Terminal 1 (Principal - Ejecución):** PowerShell en la raíz del proyecto `consultia-cascada`.
2. **Terminal 2 (Logs en vivo):** Para ver el comportamiento interno del Gateway y la API.
   ```powershell
   docker compose logs -f gateway api
   ```
3. **Terminal 3 (Métricas de contenedores):** Para ver consumo de CPU, RAM y PIDs.
   ```powershell
   docker stats
   ```

> 💡 **Verificación de 10 segundos antes de empezar:**  
> Asegúrate de que el entorno vulnerable esté arriba y saludable:  
> `curl http://localhost:8080/health` (debe responder `{"service":"api","status":"ok"}`).

---

## 🎬 2. Guión paso a paso: Simulación en Vivo

---

### Bloque A: Reconocimiento perimetral y Aislamiento de Red (~30 s)

#### ⌨️ Comando a ejecutar (en Terminal 1):
```powershell
docker compose --profile tools exec tester nmap -sV -p 8080,5000,5001,5002,5432 gateway api llm stt db
```

#### 🗣️ Qué decir:
> *"Buenos días profesor y compañeros. Como responsable de la simulación y métricas (Persona 2), lo primero que evaluamos es la superficie de ataque del sistema mediante un reconocimiento de red con Nmap desde el contenedor `tester`, ubicado en la red externa `frontend`.*
>
> *(Esperar a que salga la salida de Nmap)*
>
> *Observen el resultado en pantalla:*
> 1. *Los microservicios internos (`api`, `llm`, `stt` y `db`) arrojaron inmediatamente `Failed to resolve`. Esto confirma que la red `backend` configurada con `internal: true` cumple con la segmentación perimetral requerida por NIST SP 800-207 (Zero Trust).*
> 2. *El único componente alcanzable es el `gateway` en el puerto `8080` con Nginx 1.27. Los puertos directos de microservicios están cerrados hacia el exterior. Toda la interacción debe pasar obligatoriamente por el proxy inverso."*

---

### Bloque B: Simulación del Fallo en Cascada — Modo "Antes" (~1 min 15 s)

#### ⌨️ Comando a ejecutar (en Terminal 1):
```powershell
.\scripts\run_scenario.ps1 antes
```

#### 🗣️ Qué decir segundo a segundo mientras corre el script:

* **[Segundos 0 al 10 — Fase Baseline / Reposo]:**
  > *"El script de prueba ejecuta tres fases automatizadas con parámetros fijos y deterministas. En estos primeros 10 segundos estamos en la fase de **Baseline**: el sistema opera con tráfico nominal. Como ven en la gráfica y registros previos, `/health`, `/citas` y `/consulta` responden con un **100 % de disponibilidad** y latencias ínfimas de entre 3 y 10 milisegundos."*

* **[Segundo 10 al 50 — Fase de Carga / Ataque de Saturación]:**
  > *(Señalar la Terminal 2 de logs o la pantalla)*  
  > *"En el segundo 10 da inicio la fase de saturación: inyectamos 40 hilos concurrentes atacando exclusivamente la ruta `/consulta`, que a su vez llama al microservicio `llm`.*
  >
  > *Aquí es donde ocurre la catástrofe del fallo en cascada. Miren con atención la Terminal 2 de logs y las sondas que monitorean `/citas`:*
  > *El endpoint `/citas` **NO utiliza inteligencia artificial ni consume al contenedor `llm`**; únicamente hace una lectura simple a PostgreSQL. Sin embargo, su disponibilidad se acaba de desplomar del **100 % al 0 %**, arrojando timeouts masivos de 5000 ms.*
  >
  > *¿Por qué sucede esto? Porque en el diseño vulnerable, la API corre con Gunicorn configurado a 8 hilos compartidos y llamadas síncronas **sin timeout** hacia el LLM. Las peticiones de `/consulta` saturan el semáforo del LLM y capturan la totalidad de los hilos de la API (*Thread Starvation*). Cuando una petición legítima intenta consultar `/citas` o `/health`, no encuentra ningún hilo disponible, se queda encolada en el socket del sistema operativo y colapsa."*

* **[Segundos 50 al 80 — Fase de Recuperación / Fallo Metaestable]:**
  > *"En el segundo 50 cesa el ataque por completo. La carga se detuvo, pero observen la terminal: el sistema reporta que **no se recuperó en la ventana medida**.*
  >
  > *Esto demuestra que el sistema entró en un estado de **fallo metaestable** (*metastable failure*): la acumulación de sockets y peticiones pendientes encoladas en Gunicorn mantiene a los trabajadores ahogados mucho después de que el tráfico agresivo haya desaparecido."*

#### 🔍 Qué destacar en los logs de la Terminal 2 (Nginx):
> *"Profesor, fíjese en este detalle crítico en los logs de Nginx: no vemos un error 504 clásico, sino el código **HTTP 499** con tiempos `rt=5.008 urt=5.008`. Esto significa **Client Closed Request**: la sonda del cliente tenía un timeout de 5 segundos y se cansó de esperar a Nginx, cortando la conexión TCP mientras Nginx seguía esperando inútilmente a una API totalmente congelada."*

---

### Bloque C: Simulación con Sistema Mitigado — Modo "Después" (~1 min)

*(Nota: Este paso se corre en vivo cuando el grupo demuestre las contramedidas de P3 y P4)*

#### ⌨️ Comandos a ejecutar:
```powershell
.\scripts\up.ps1 hardened
.\scripts\run_scenario.ps1 despues
```

#### 🗣️ Qué decir:
> *"Ahora levantamos el entorno endurecido mediante `docker-compose.hardened.yml`, donde mis compañeros P3 y P4 implementaron las defensas arquitectónicas.*
>
> *(Ejecutar `run_scenario.ps1 despues`)*
>
> *Lanzamos exactamente la misma prueba bajo las mismas condiciones: 40 hilos atacando `/consulta`.*
>
> *Miren la diferencia radical en los resultados:*
> 1. ***Load Shedding en Gateway:** Nginx rechaza el exceso de tráfico devolviendo inmediatamente código **HTTP 429 (Too Many Requests)**, evitando que la avalancha llegue a asfixiar a la API.*
> 2. ***Aislamiento por Bulkhead y Circuit Breaker:** Dentro de la API, el Bulkhead limita a máximo 4 hilos las llamadas hacia el LLM, garantizando que siempre existan hilos libres y dedicados exclusivamente para atender `/citas` y `/health`.*
> 3. ***Disponibilidad preservada:** Mientras `/consulta` degrada elegantemente con error controlado y cabecera `Retry-After`, **la disponibilidad de `/citas` se mantiene prácticamente al 100 %** y con latencias de milisegundos.*
> 4. ***Tiempo de recuperación inmediato:** Tan pronto termina la carga, el sistema está 100 % operativo sin necesidad de reinicios manuales."*

---

### Bloque D: Cierre y pase de palabra (~15 s)

#### 🗣️ Qué decir:
> *"Con esto dejamos demostrado empírica y numéricamente cómo una falla local no contenida derriba un sistema completo, y cómo la arquitectura resiliente desacopla los fallos. Le cedo la palabra a mi compañero/a para profundizar en el diseño de los patrones de resiliencia y seguridad Zero Trust."*

---

## 🧠 3. Banco de Preguntas Difíciles del Profesor (y cómo responderlas con soltura)

### Pregunta 1: *"¿Por qué se cayó `/citas` si la base de datos PostgreSQL nunca estuvo saturada?"*
* **Respuesta técnica perfecta:**  
  *"Porque el cuello de botella no fue de almacenamiento ni de la base de datos, sino un agotamiento de recursos compartidos en la capa de aplicación (*Thread Starvation*). Gunicorn administra un pool único de 8 hilos para todo el proceso. Al no existir un timeout entre la API y el LLM, cada petición a `/consulta` acaparó un hilo indefinidamente. Al llegar peticiones a `/citas`, no había hilos libres en el worker pool para procesar la consulta SQL, quedando congeladas en el socket del servidor."*

### Pregunta 2: *"¿Por qué en los logs de Nginx aparece código 499 y no un 504 Gateway Timeout o 502 Bad Gateway?"*
* **Respuesta técnica perfecta:**  
  *"El código HTTP 499 es propio de Nginx y significa `Client Closed Request`. Ocurre porque el timeout configurado en nuestro cliente de pruebas (`tester` con `requests.get`) era de 5 segundos para sondas y 30 segundos para carga, mientras que en el Nginx vulnerable el `proxy_read_timeout` era de 60 segundos. Al tardar la API más de 5 segundos en responder, fue el cliente quien abortó activamente la conexión TCP enviando un FIN/RST antes de que Nginx alcanzara su propio timeout de 60 s."*

### Pregunta 3: *"¿Por qué durante la carga la disponibilidad de `/consulta` no fue 0 %, sino 14 %?"*
* **Respuesta técnica perfecta:**  
  *"Porque el microservicio simulado de LLM tiene un semáforo con `MAX_CONCURRENCY=2` y una latencia de 2000 ms. Esto significa que el LLM es capaz de procesar con éxito aproximadamente una petición por segundo. Las pocas peticiones que lograron entrar al semáforo justo a tiempo antes de que expiraran los timeouts lograron completarse con código 200, mientras que el restante 86 % de solicitudes concurrentes expiró en cola."*

### Pregunta 4: *"¿Por qué el sistema no se recuperó solo cuando terminó la carga en el escenario vulnerable?"*
* **Respuesta técnica perfecta:**  
  *"Porque entró en un estado de fallo metaestable (*metastable failure*). Aunque el generador de carga cesó en el segundo 50, quedaron decenas de peticiones represadas en el backlog de la cola TCP del socket de Gunicorn. Como los hilos continuaban ejecutando llamadas lentas pendientes hacia el LLM, el servidor tardó más tiempo del medido en drenar la cola acumulada, impidiendo atender las nuevas solicitudes de sondeo."*

### Pregunta 5: *"¿Una política de `restart: always` en Docker resolvería este problema en producción?"*
* **Respuesta técnica perfecta:**  
  *"No, profesor, de hecho lo empeoraría gravemente. Si reiniciamos el contenedor `api` o `llm` bajo carga sostenida, el servicio se levanta en frío con cachés vacías y conexiones cerradas, recibiendo instantáneamente la misma avalancha de peticiones acumuladas. Esto genera un ciclo vicioso de reinicios continuos (*crash loop*). La solución real debe ser arquitectónica: Timeouts, Bulkhead, Circuit Breaker y Load Shedding."*

---

## 🛟 4. Plan de Contingencia (Plan B)

Si durante la presentación en vivo ocurre un imprevisto (ejemplo: Docker Desktop se traba, la laptop se queda sin batería o hay un fallo de red local):

1. **Mantén la calma y no intentes depurar código en vivo.**
2. Abre inmediatamente la carpeta `evidencias/antes/` y proyecta los archivos ya generados:
   - Muestra **`antes_resumen_terminal.png`** y di: *"Para garantizar la reproducibilidad y optimizar el tiempo, aquí tenemos la captura de la ejecución determinista del script donde se aprecia la tabla con 0 % de disponibilidad."*
   - Muestra **`latencia.png`** y explica la curva del salto a 5000 ms.
   - Muestra **`antes_logs_cascada.png`** para sustentar el error 499 y los tiempos de upstream.
3. El plan de trabajo contempla explícitamente este respaldo: tener las evidencias estáticas y las capturas listas demuestra previsión profesional y rigor de ingeniería.
