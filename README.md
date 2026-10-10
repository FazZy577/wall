# Wallapop Arbitrage Platform

Motor de análisis de oportunidades de videojuegos en Wallapop con una CLI
operativa para ejecutar búsquedas configuradas. El flujo actual genera planes
canónicos de búsqueda, deduplica candidatos, detecta juegos, valora
comparables y calcula oportunidades individuales y de lotes. Antes de enviar
un candidato a los scanners, una política de elegibilidad separa juegos
incluidos de referencias contextuales y clasifica hardware, accesorios,
ediciones no modeladas y menciones multiplataforma inseguras.

La CLI realiza consultas reales únicamente cuando se ejecuta `scan` con
`--confirm-live`. Puede conservar observaciones e identificaciones en SQLite
mediante `[persistence]`. No es todavía un sistema autónomo: no hay scheduler,
notificaciones, API ni dashboard.

## Instalación mínima

Requisitos: Python 3.11+ y [uv](https://docs.astral.sh/uv/).

```powershell
py -m uv sync --extra dev
py -m uv run playwright install chromium
```

La configuración de referencia está en [`config.example.toml`](config.example.toml).
Para buscar sin una lista de juegos, usa
[`config.discovery.example.toml`](config.discovery.example.toml): descubre anuncios
por categoría y, opcionalmente, por palabras de plataforma. Conserva desconocidos
en SQLite y muestra los límites de cobertura de cada consulta.
El registro local separa juego y lanzamiento mediante IDs estables; conserva
desconocidos como provisionales y distingue Nintendo Switch de Nintendo Switch 2.
Con `[metadata] enabled = true`, el proveedor opcional IGDB puede confirmar
juegos ausentes de la semilla, conservar su procedencia y reconocerlos después
sin editar el catálogo. Requiere credenciales y persistencia; consulta la
[configuración y los límites de B09](OPERATIONAL_CLI.md#identificación-externa-opcional-b09).
La caché persistente limita consultas repetidas y revisa pendientes y metadatos
caducados al iniciar los escaneos. Con `persistence.seed_catalog = false` y
descubrimiento con metadatos activos, puede empezar sin una lista inicial de juegos.

## Uso principal

```powershell
wallapop-arbitrage --help
wallapop-arbitrage --version
wallapop-arbitrage scan --config config.toml --confirm-live
```

La misma CLI puede ejecutarse como módulo:

```powershell
py -m uv run python -m presentation.cli scan --config config.toml --confirm-live
```

Consulta [`OPERATIONAL_CLI.md`](OPERATIONAL_CLI.md) para el esquema TOML,
salidas terminal/JSON, códigos de salida, seguridad y troubleshooting.

La generación de consultas es automática pero determinista: no utiliza IA,
LLM, embeddings ni aliases inventados.

## Desarrollo

```powershell
py -m uv run pytest -m "not live"
py -m uv run mypy src
py -m uv run ruff check src tests examples
```

Los tests live son opt-in mediante `RUN_LIVE_WALLAPOP_TESTS=1`; no forman parte
de la validación normal.

## Arquitectura

```text
Domain → Application → Infrastructure
                         ↑
                    Presentation/CLI
```

Presentation compone la configuración, el lifecycle de Playwright y los
casos de uso. Domain y Application no dependen de Presentation. El detalle de
capas se encuentra en [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Estado

El motor de análisis y la CLI operativa están implementados y cubiertos por
tests offline. Los candidatos `ignored` y `ambiguous` son resultados esperados
del routing y se muestran separados de los fallos técnicos en terminal y JSON
schema v2. La estructura versionada del catálogo declara siete plataformas;
PS3 contiene 141 juegos reales, PS4 contiene 50, PS5 incorpora 145, Xbox 360
incorpora 126, Xbox One incorpora 146, Xbox Series incorpora 120 y Nintendo
Switch incorpora 119. Las siete plataformas del roadmap disponen ya de datos
reales. El catálogo Nintendo corresponde exclusivamente a Switch original;
Switch 2 queda fuera de alcance hasta decidir si requiere un valor propio en
`Platform`.
Quedan pendientes la persistencia
histórica, la programación de ejecuciones, notificaciones, búsqueda de mercado
completo, aliases seguros, liquidez, calibración y una futura API/dashboard.
