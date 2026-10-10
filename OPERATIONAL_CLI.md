# Operational CLI

La CLI operativa ejecuta un escaneo explícitamente configurado contra
Wallapop. Genera un `SearchPlan`, ejecuta el `SearchOrchestrator` existente y
presenta el resultado en terminal y, opcionalmente, en JSON. No es todavía un
sistema autónomo: no programa ejecuciones, no envía
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

## Identidades y registro local (B08)

Un juego tiene un `game_id` estable. Sus lanzamientos/productos tienen un
`release_id`, plataforma, edición y formato propios. El nombre y los alias son
metadatos: renombrarlos no cambia la identidad ni la clave de caché. Dos versiones
para plataformas distintas, o productos con edición o formato diferentes, no
comparten identidad para los comparables.

Con persistencia activa, las tablas `games`, `game_releases` y
`external_game_references` guardan este registro. Si todavía no hay lanzamientos
confirmados, se importa la semilla empaquetada con sus IDs explícitos; un registro
local ya poblado funciona sin cargar el JSON inicial. Reimportar la semilla
conserva los nombres y estados locales y rechaza conflictos de IDs. Los IDs están
versionados también en `catalog/platforms/`, por lo que regenerar el artefacto no
los cambia. Al renombrar un juego de la semilla se deben conservar sus IDs.

Los desconocidos observados reciben un registro `provisional`, enlazado mediante
`listing_observations.provisional_game_id`. Es una hipótesis asociada al anuncio,
no una afirmación de que cada anuncio corresponda a un juego distinto. No se
fusionan automáticamente anuncios por parecido textual. Al iniciar, se enlazan
también observaciones antiguas cuyo último estado sea desconocido, sin incrementar
sus contadores. El histórico anterior se conserva sin inventar identidades
confirmadas para sus evidencias.

Los provisionales quedan fuera del catálogo de detección y no pueden entrar en
la valoración. Si llegan explícitamente al clasificador, se señalan como
`unconfirmed_identity`. Las referencias externas son opcionales y su combinación
proveedor/ID es única; B08 no hace llamadas a proveedores.

«Nintendo Switch 2» es una plataforma distinta de «Nintendo Switch», incluso en
el reconocimiento del texto. No se trasladan juegos ni precios de una a otra.
El modelo permite guardar otras ediciones y formatos, pero el flujo de valoración
continúa limitado a la edición estándar física: registrar una edición especial
no activa por sí solo su reconocimiento o valoración.

Los contratos antiguos construidos sin IDs siguen siendo legibles para facilitar
la migración. Sus claves por nombre no se equiparan a claves registradas: un nombre
coincidente por sí solo no autoriza a mezclar sus precios.

## Descubrimiento sin nombres de juegos (B07)

La configuración completa está en `config.discovery.example.toml`. Copia ese
ejemplo a tu configuración de trabajo. Sustituye la sección `[search]` del modo
anterior y elimina sus bloques `[[search.targets]]`:

```toml
[search]
strategy = "discovery"
max_queries = 4
max_results_per_query = 20
discovery_platforms = []
```

La lista vacía busca en toda la categoría «Consolas y Videojuegos», sin exigir
nombres conocidos. Para consultas más acotadas puedes usar, por ejemplo,
`discovery_platforms = ["PS4", "PS5"]`. Cada plataforma genera una consulta por
palabra clave: no se presenta como un filtro nativo de plataforma ni garantiza
que todos los resultados sean de esa consola. La clasificación posterior sigue
comprobando el producto y su identidad. Los nombres de juegos no intervienen en
la generación del plan de descubrimiento.

La ubicación usa `location.latitude` y `location.longitude`. No se promete un
radio geográfico estricto: B07 no añade un parámetro de distancia sin verificar.
Los límites siguen siendo `search.max_queries`, `search.max_results_per_query`
y `wallapop.max_pages`. Las búsquedas de títulos concretos siguen disponibles con
`strategy = "canonical_only"` y `[[search.targets]]`.

Verificación de filtros, 2026-10-02: la
[página oficial de Consolas y Videojuegos](https://es.wallapop.com/consolas-y-videojuegos)
incluye en `seoLandingSearchParams` los valores `category_id=24200` y
`subcategory_ids=24203`; B07 usa esos parámetros, no el identificador antiguo
12900. La [ayuda oficial de filtros](https://ayuda.wallapop.com/hc/es-es/articles/360002048677-Usar-filtros-de-b%C3%BAsqueda)
describe categoría y distancia, pero no documenta un filtro nativo de plataforma
de consola. Esta comprobación de la web no equivale a una prueba live del navegador.

### Cobertura de las búsquedas

El terminal y el JSON (`execution.query_scans`, campo adicional del esquema 2)
registran cada consulta ejecutada, ubicación, categoría solicitada, límites,
fechas, páginas recibidas y motivo de parada. Con `[persistence].enabled = true`,
los mismos datos quedan en SQLite, tabla `query_scans`, agrupados por `run_id`.
Las consultas duplicadas se eliminan antes de ejecutarse y su contador se mantiene.

- `exhausted`: el servidor indicó fin de paginación de esa consulta.
- `result_limit` / `page_limit`: se alcanzó el límite local; la cobertura es limitada.
- `pagination_unknown`: la respuesta no declara si quedan páginas.
- `unreported`: un cliente alternativo no proporciona métricas de cobertura.
- `error`: la consulta falló; puede conservar las páginas recibidas antes del fallo.

`exhausted` no significa haber leído todo Wallapop. Se refiere solo a los
resultados ofrecidos para esos filtros y esa ubicación en ese momento. Si falla
una página posterior, la consulta continúa tratándose como fallida y no se
valoran sus resultados parciales. Un fallo al guardar cobertura se publica como
`scan_storage_error`; el informe mantiene las métricas en memoria.

Los anuncios desconocidos recibidos se registran mediante B06. La resolución
automática de su identidad y la incorporación al catálogo corresponden a bloques
posteriores; un desconocido no se convierte en una recomendación BUY.

## Ejecución

### Persistencia de observaciones (B06)

```toml
[persistence]
enabled = true
database_path = "data/catalog_discovery.sqlite3"
```

La ruta es relativa al TOML. Si se omite la sección, la persistencia queda
desactivada; `config.example.toml` la activa explícitamente. Cargar el TOML no
escribe archivos. El runtime crea el directorio y la base de datos al iniciarse.

Se guardan los candidatos recibidos, incluidos desconocidos, ambiguos y errores
de identificación, y los comparables aceptados con su consulta de origen.
`listing_observations` conserva texto, precio, moneda y versiones por anuncio;
`listing_identifications` conserva estados, evidencias, fechas e intentos de
procesamiento local. `listing_observation_queries` conserva la primera consulta
que aportó cada candidato y las consultas de los comparables.

Repetir un anuncio idéntico actualiza fechas y contadores sin duplicar su versión.
Cambiar texto o precio crea otra versión; cambiar la identificación conserva la
evidencia anterior. No se guardan datos estructurados del vendedor ni el payload
original, aunque el texto del anuncio se conserva tal como se recibió.
Las antiguas tablas de títulos agregados se mantienen intactas.

Un fallo de inicialización termina con código `8`. Un fallo al guardar candidatos
aparece como `observation_storage_error` en terminal y JSON y produce código `1`;
el resto del escaneo continúa. Los fallos al guardar comparables se propagan al
scanner y aparecen entre sus fallos. Los datos no escritos no se consideran guardados.

Este bloque conserva desconocidos que lleguen al flujo actual. La búsqueda por
categoría sin exigir títulos conocidos corresponde a B07; B06 no identifica ni
añade automáticamente juegos al catálogo.

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
oportunidades individuales, resultados de lotes, candidatos ignorados,
candidatos ambiguos, fallos y resumen. `ignored` significa que la política ha
identificado un anuncio que no debe valorarse (por ejemplo hardware, accesorio
o referencia contextual). `ambiguous` significa que no puede asumirse con
seguridad la identidad valorable (por ejemplo múltiples plataformas o una
edición no modelada). Ambos son resultados esperados, no fallos técnicos. El
renderer sanea texto externo y no recalcula economía ni ranking.

Si `output.json_path` está configurado, se genera un informe JSON con esquema
versión `2`. Incluye `ignored_candidates` y `ambiguous_candidates` con sus
contadores, incluso como arrays vacíos, separados de `failures`. Los importes
`Decimal` se representan como strings, las URLs se
limpian de query y fragmentos, y no se incluyen `raw_listing`, cookies,
headers, tokens ni tracebacks. El writer serializa completamente en memoria y
reemplaza el destino mediante un archivo temporal del mismo directorio y
`os.replace()`. No crea el directorio padre.

Si existe destino JSON, el orden operativo es: cargar configuración, ejecutar
el preflight, abrir el runtime, escanear, cerrar el runtime, construir el
informe y escribirlo. El preflight rechaza antes de abrir Playwright un padre
inexistente, un target que sea directorio o un target existente cuando
`overwrite=false`. El writer revalida porque el filesystem puede cambiar entre
ambos pasos. Si JSON está deshabilitado no se ejecuta preflight.

El JSON es un informe de ejecución, no persistencia histórica.

## Códigos de salida

| Código | Significado |
|---:|---|
| 0 | Éxito o búsqueda vacía válida; `ignored`/`ambiguous` sin fallo técnico |
| 1 | Resultado parcial con fallos y datos utilizables |
| 2 | Argumentos inválidos o falta `--confirm-live` |
| 3 | Configuración inválida o ilegible |
| 4 | Target de juego desconocido |
| 5 | Límite del plan excedido |
| 6 | Fallo total del marketplace/lifecycle |
| 7 | Fallo de preflight o escritura del informe JSON |
| 8 | No se pudo inicializar la base de observaciones |
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
Playwright. Incorpora persistencia opcional y metadatos externos opcionales;
no incorpora IA generativa, scheduler, reintentos programados, notificaciones,
API ni dashboard. Ejecuta el alcance configurado de búsqueda o descubrimiento.

Los aliases de detección se reconocen con límites léxicos; no se usan para
generar consultas. La política de elegibilidad evita valorar hardware,
accesorios, copias incompletas y referencias contextuales, y mantiene como
ambiguas las ediciones no soportadas o menciones multiplataforma. Reconocer
estas menciones para seguridad de routing no implica soporte de valoración:
se valoran únicamente juegos físicos de edición estándar y plataforma identificada.

Riesgo residual: con `overwrite=false`, otro proceso podría crear el target
entre el preflight y el `os.replace()` final. Esta ventana TOCTOU se clasifica
como riesgo medio de filesystem y no bloquea P4.5.

Si falla la configuración, comprueba que el TOML tiene todas las secciones y
que los importes económicos son strings. Si falla Chromium, ejecuta de nuevo
`py -m uv run playwright install chromium`. Para separar un fallo parcial de
uno total, revisa el código de salida y las secciones `FAILURES` del informe.

## Identificación externa opcional (B09)

El adaptador inicial consulta IGDB v4 mediante el contrato intercambiable
`IGameMetadataProvider`. No utiliza un LLM ni obtiene precios de IGDB: los precios
siguen procediendo de comparables del marketplace.

En el TOML, mantén `[persistence] enabled = true` y activa:

```toml
[metadata]
enabled = true
provider = "igdb"
```

Configura `IGDB_CLIENT_ID` e `IGDB_CLIENT_SECRET` en el entorno del proceso.
Son las credenciales de una aplicación confidencial registrada en Twitch;
el adaptador obtiene y renueva el token de aplicación. No pongas secretos en
el TOML, el repositorio o los informes. Con la opción desactivada no se consulta
IGDB. Activarla sin credenciales deja los nuevos juegos pendientes y registra
un fallo parcial, sin detener los conocidos.

La [documentación oficial de IGDB](https://api-docs.igdb.com/) describe registro,
autenticación y condiciones: el uso gratuito es no comercial; para integraciones
comerciales indica un acuerdo con IGDB. Comprueba las condiciones aplicables al
uso del bot antes de habilitar consultas reales.

La resolución exige una plataforma explícita en el título, coherente con la
descripción, y un nombre completo coincidente con un nombre del proveedor.
Conserva números y subtítulos; no confirma por similitud. Solo admite un resultado
compatible, sin DLC, bundles ni ediciones especiales. La política del anuncio
vuelve a comprobar contenido y venta antes de registrar un lanzamiento físico
estándar. Esta comprobación textual no certifica el estado real del producto.
Títulos con ruido adicional, lotes desconocidos, plataformas no soportadas o
metadatos insuficientes pueden quedar pendientes.
Con esta opción activa, una coincidencia local que solo cubre parte del título
también exige confirmación: un subtítulo nuevo no puede valorarse con los precios
del juego original si IGDB falla. Esto puede dejar pendientes títulos conocidos
con texto comercial adicional que todavía no se pueda separar con seguridad.

La transacción SQLite guarda identidad, referencia externa y evidencia en
`metadata_resolutions`, incluyendo consulta, título, descripción, candidatos,
estado y fecha UTC. Los estados son `confirmed`, `not_found`, `ambiguous`,
`unsupported_content`, `unsupported_listing` y `provider_error`. Los registros
provisionales previos se conservan como historia; la evidencia confirmada enlaza
los IDs definitivos. Solo se guardan como aliases nombres recibidos del proveedor,
nunca el texto comercial del vendedor. Los homónimos locales sin referencia
externa común no se fusionan automáticamente.

La detección comparte el registro actualizado con los colectores de comparables
en la misma ejecución. Tras reiniciar, los juegos confirmados se reconocen sin
consultar de nuevo al proveedor. Sus IDs son independientes del nombre.

Cada búsqueda devuelve como máximo 49 candidatos completos; una respuesta que
alcanza el límite de 50 se considera incompleta y no confirma identidades.
El adaptador serializa sus solicitudes, separa consultas 300 ms y aplica un
timeout de 15 s por operación HTTP. Los fallos aparecen como
`metadata_resolution_error` en el informe y salida parcial `1`.
La caducidad de metadatos, presupuestos globales, reintentos de pendientes y
deduplicación de consultas fallidas se describen en B10, a continuación.
Los presupuestos globales del marketplace siguen pendientes de B12.

Validación de B09: pruebas offline con SQLite real y transporte HTTP simulado.
No se han realizado consultas autenticadas a IGDB ni un escaneo real de Wallapop.

## Actualización y reintentos controlados (B10)

La caché SQLite se comparte entre anuncios y entre ejecuciones. Guarda respuestas
del proveedor, no decisiones de elegibilidad: cada anuncio vuelve a comprobarse
antes de confirmar un lanzamiento. Su clave incluye proveedor y nombre extraído;
la plataforma se contrasta con los candidatos de la respuesta en cada resolución.

Parámetros de `[metadata]`, con sus valores predeterminados:

| Parámetro | Valor | Función |
| --- | --- | --- |
| `max_queries_per_scan` | `20` | Máximo de búsquedas externas, incluidos intentos fallidos y mantenimiento |
| `maintenance_limit` | `5` | Máximo de observaciones antiguas revisadas al iniciar un escaneo; `0` lo desactiva |
| `metadata_ttl_seconds` | `604800` | Caducidad de respuestas confirmadas: siete días |
| `pending_retry_seconds` | `86400` | Intervalo de pendientes, ambiguos y resultados incompatibles: un día |
| `error_retry_seconds` | `300` | Espera tras fallos del proveedor: cinco minutos |

Leer una respuesta de caché no consume una búsqueda ni retrasa su vencimiento.
Una respuesta negativa o un error mantiene su plazo aunque se reinicie el bot.
Los estados de resolución distinguen `not_found`, `ambiguous` y `provider_error`.
`deferred` indica presupuesto agotado o consulta ya en curso en otro proceso.
La tabla `metadata_query_cache` registra el plazo; `metadata_resolutions` conserva
la evidencia de identificación. Una reclamación temporal de cinco minutos evita
duplicar solicitudes concurrentes y permite recuperarse de procesos interrumpidos.

Al comenzar cada escaneo se revisan observaciones vencidas de
`metadata_watchlist`. El mantenimiento utiliza como máximo la mitad del
presupuesto, con un mínimo de una búsqueda si el presupuesto total es uno y
el mantenimiento está activo. El resto queda disponible para anuncios nuevos.
No hay proceso permanente ni temporizador en segundo plano: los pendientes se
reintentan en el siguiente escaneo que se ejecute después de su plazo.

La migración inicial recupera observaciones pendientes de B06–B09 y respeta los
plazos de intentos anteriores. No modifica la evidencia histórica. Un pendiente
puede resolverse aunque su anuncio no vuelva a aparecer; esto solo actualiza la
identidad local. **Los anuncios históricos no se envían a valoración ni generan
recomendaciones de compra.**

Actualizar una referencia externa ya registrada conserva IDs y nombre local.
Puede incorporar nombres alternativos recibidos del mismo proveedor, pero nunca
texto comercial del vendedor. Si los nombres nuevos chocan con otra identidad,
la actualización queda ambigua y no se mezclan juegos. Las respuestas
incompatibles o los fallos no borran identidades previamente confirmadas.

Para arrancar sin la semilla de juegos, utiliza la estrategia `discovery` y:

```toml
[persistence]
enabled = true
database_path = "data/catalog_discovery.sqlite3"
seed_catalog = false

[metadata]
enabled = true
provider = "igdb"
```

Necesita las credenciales de IGDB indicadas en B09. Una base vacía puede descubrir,
identificar y conservar juegos sin leer los archivos del catálogo inicial.
`seed_catalog=false` no elimina juegos que ya existan en la base. Si se mantiene
`true`, se conserva la inicialización con semilla de los bloques anteriores.

Este presupuesto cuenta búsquedas de metadatos; no incluye la autenticación de
Twitch ni las consultas de Wallapop. Su control global corresponde a B12.
