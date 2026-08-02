# Operational CLI

La CLI operativa ejecuta un escaneo explícitamente configurado contra
Wallapop. Genera un `SearchPlan`, ejecuta el `SearchOrchestrator` existente y
presenta el resultado en terminal y, opcionalmente, en JSON. No es todavía un
sistema autónomo: no persiste histórico, no programa ejecuciones, no envía
notificaciones y no ofrece API ni dashboard.

## Requisitos e instalación

Se requiere Python 3.11 o posterior y `uv`.

```powershell
py -m uv sync --extra dev
py -m uv run playwright install chromium
```

El segundo comando instala el navegador gestionado por Playwright. La CLI no
abre el navegador al mostrar ayuda o versión; solo lo hace al ejecutar `scan`
con confirmación explícita.

## Configuración TOML

Parte de [`config.example.toml`](config.example.toml). La configuración es
inmutable, estricta y no lee variables de entorno. Los targets son nombres
canónicos y plataformas explícitas; la estrategia actual es
`canonical_only`. La economía requiere tasas, costes y umbrales explícitos por
moneda, por ejemplo `EUR`. Los importes se escriben como strings decimales.

Los campos principales son:

- `[wallapop]`: `headless`, `timeout_ms`, `max_pages` y `request_delay`.
- `[location]`: `latitude` y `longitude`.
- `[search]`: `strategy`, `max_queries`, `max_results_per_query` y
  `[[search.targets]]`.
- `[economics]`: tasas globales y `[[economics.currencies]]`.
- `[output]`: `terminal`, `json_path` y `overwrite`.
- `[safety]`: `max_targets`.

Las rutas JSON relativas se resuelven respecto al archivo TOML. El loader no
crea directorios. `reports/` está ignorado por Git para resultados locales.

## Ejecución

Tras instalar el proyecto, el console script es:

```powershell
wallapop-arbitrage --help
wallapop-arbitrage --version
wallapop-arbitrage scan --config config.toml --confirm-live
```

También puede utilizarse el módulo:

```powershell
py -m uv run python -m presentation.cli --help
py -m uv run python -m presentation.cli --version
py -m uv run python -m presentation.cli scan --config config.toml --confirm-live
```

`--confirm-live` es obligatorio para acceder al marketplace. Sin él, la CLI
termina con código `2` antes de cargar la configuración o crear el runtime.
`--verbose` habilita logging informativo; por defecto solo se muestran
warnings.

## Salidas

La salida terminal contiene las secciones de generación, ejecución,
oportunidades individuales, resultados de lotes, fallos y resumen. El renderer
no recalcula economía ni ranking.

Si `output.json_path` está configurado, se genera un informe JSON con esquema
versión `1`. Los importes `Decimal` se representan como strings, las URLs se
limpian de query y fragmentos, y no se incluyen `raw_listing`, cookies,
headers, tokens ni tracebacks. El writer serializa completamente en memoria y
reemplaza el destino mediante un archivo temporal del mismo directorio y
`os.replace()`. No crea el directorio padre.

El JSON es un informe de ejecución, no persistencia histórica.

## Códigos de salida

| Código | Significado |
|---:|---|
| 0 | Éxito o búsqueda vacía válida |
| 1 | Resultado parcial con fallos y datos utilizables |
| 2 | Argumentos inválidos o falta `--confirm-live` |
| 3 | Configuración inválida o ilegible |
| 4 | Target de juego desconocido |
| 5 | Límite del plan excedido |
| 6 | Fallo total del marketplace/lifecycle |
| 7 | Error escribiendo el informe JSON |
| 70 | Error interno inesperado |
| 130 | Cancelación o `KeyboardInterrupt` |

Una consulta vacía es una ejecución válida. Un fallo técnico de una consulta
no borra los éxitos de las demás; si todas fallan sin resultado utilizable se
devuelve `6`.

## Tests live opt-in

Los tests live no se ejecutan normalmente. El smoke test de la CLI requiere
una única variable de opt-in y usa una configuración temporal limitada:

```powershell
$env:RUN_LIVE_WALLAPOP_TESTS="1"
py -m uv run pytest tests/e2e/test_cli_live.py -v
Remove-Item Env:RUN_LIVE_WALLAPOP_TESTS
```

No exige una oportunidad ni una recomendación concreta. Sí exige que el
comando termine sin error de argumentos, configuración, marketplace, JSON o
cancelación, que se emitan las secciones principales y que no quede salida de
debug. El lifecycle del cliente pertenece al composition root y se cierra al
finalizar la ejecución.

## Seguridad y limitaciones

La CLI no guarda cookies, headers, respuestas de depuración ni perfiles
Playwright. No incorpora IA, aliases automáticos, persistencia, scheduler,
reintentos, concurrencia, notificaciones, histórico, liquidez, API o
dashboard. Solo se ejecutan los targets y consultas definidos por el operador.

Si falla la configuración, comprueba que el TOML tiene todas las secciones y
que los importes económicos son strings. Si falla Chromium, ejecuta de nuevo
`py -m uv run playwright install chromium`. Para separar un fallo parcial de
uno total, revisa el código de salida y las secciones `FAILURES` del informe.
