# Resumen del escenario: antes

| Fase | Endpoint | Peticiones | Disp. (200) | 429 (rate limit) | 5xx / timeout | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|
| baseline | /health | 10 | 100 % | 0 | 0 | 3 | 11 |
| baseline | /citas | 10 | 100 % | 0 | 0 | 10 | 26 |
| baseline | /consulta | 3 | 100 % | 0 | 0 | 2115 | 2158 |
| carga | /health | 6 | 0 % | 0 | 6 | 5008 | 5032 |
| carga | /citas | 6 | 0 % | 0 | 6 | 5007 | 5010 |
| carga | /consulta | 7 | 14 % | 0 | 6 | 5008 | 5011 |
| recuperacion | /health | 5 | 0 % | 0 | 5 | 5010 | 5013 |
| recuperacion | /citas | 5 | 0 % | 0 | 5 | 5008 | 5014 |
| recuperacion | /consulta | 5 | 0 % | 0 | 5 | 5007 | 5014 |

**Tiempo de recuperacion de /citas tras la carga:** no se recupero en la ventana medida
