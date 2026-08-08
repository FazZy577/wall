# Arquitectura del Proyecto

## Decimal monetary boundary (P1.11)

Canonical prices, costs, revenues, financial rates, thresholds, statistics,
outlier bounds and market estimates use `decimal.Decimal`. Wallapop values are
normalized once in Infrastructure: strings with `Decimal(text)`, integers with
`Decimal(integer)`, and unavoidable JSON floats with `Decimal(str(value))`.
Domain rejects floats. Scores, confidence and coordinates remain `float`, and
counts remain `int`; Application performs no external monetary parsing.

There is no `Money` object, currency conversion, cent quantization, commercial
rounding or global Decimal-context override. Currency remains metadata and JSON
serialization of Decimal remains a future API decision.

## Visión General

Plataforma para detectar oportunidades de arbitraje en marketplaces de segunda mano, comenzando con Wallapop y preparada para expandirse a otros marketplaces (Vinted, Milanuncios, eBay, etc.).

## Principios Arquitectónicos

### Clean Architecture / Arquitectura Hexagonal

El proyecto sigue los principios de Clean Architecture con tres capas principales:

1. **Domain Layer** (Núcleo)
   - Entidades del dominio
   - Value Objects
   - Interfaces (Ports)
   - Lógica de negocio pura
   - **Sin dependencias externas**

2. **Application Layer** (Casos de Uso)
   - Orquestación de casos de uso
   - Coordinación entre dominio e infraestructura
   - Depende solo del Domain Layer

3. **Infrastructure Layer** (Adaptadores)
   - Implementaciones concretas de interfaces
   - Adaptadores de marketplace (Wallapop, Vinted, etc.)
   - Repositorios de base de datos
   - Clientes HTTP, etc.
   - Depende de Domain y Application

### Regla de Dependencias

```
Infrastructure → Application → Domain
                              ↑
                              |
                    (no depende de nadie)
```

La orquestación de escaneos pertenece a Application. Sus casos de uso reciben
puertos por constructor y no conocen Wallapop, Playwright ni implementaciones
concretas de Infrastructure.

## P2 Search orchestration

`DefaultSearchOrchestrator` es un caso de uso adicional de Application. Recibe
`ICandidateSearch`, `IGameDetector`, `IOpportunityScanner` e
`ILotOpportunityScanner` por inyección; no importa adaptadores de
Infrastructure ni instancia clientes concretos. Su ejecución es secuencial y
determinista: deduplica `SearchQuery`, obtiene `CandidateListing`, deduplica
por `listing_id`, detecta una vez por candidato y dirige los candidatos al
scanner individual o al scanner de lotes.

Los resultados permanecen separados: `SearchOrchestrationResult` contiene un
`ScanResult` opcional para el batch individual, una tupla de `LotScanResult` y
fallos de consulta, de item y de routing. El orquestador no vuelve a rankear;
`DefaultOpportunityScanner` sigue delegando el ranking individual a su
`IOpportunityRanker` inyectado. Tampoco calcula comparables, estadísticas,
outliers, estimaciones o economía.

El lifecycle de marketplace es externo al caso de uso. Un entry point puede
compartir una instancia de `WallapopPlaywrightClient` entre
`WallapopCandidateSearchAdapter` y `WallapopPriceCollector` dentro de un
`async with`; el orquestador no abre/cierra Playwright, no controla el event
loop y no usa `asyncio.run()`. No hay persistencia, reintentos, aliases
automáticos ni concurrencia.

El routing productivo incluye `ICandidateEligibilityPolicy` entre la detección
preliminar y los scanners. `CandidateClassification` devuelve una disposición,
un motivo estable y `included_games`: solo estos juegos confirmados llegan a
`scan_detected_multiple()` o `scan_detected_lot()`. Hardware, accesorios y
referencias contextuales se ignoran; las menciones multiplataforma y ediciones
no modeladas quedan ambiguas. `ignored` y `ambiguous` son resultados terminales
esperados, no fallos técnicos. Los fallos del detector, de la política o de los
scanners permanecen en `routing_failures` y no detienen los candidatos
posteriores.

```text
CandidateListing
        -> FuzzyGameDetector (detecciones preliminares con límites léxicos)
        -> ICandidateEligibilityPolicy
        -> CandidateClassification
                -> eligible individual -> individual scanner
                -> eligible lot        -> lot scanner
                -> ignored             -> resultado esperado
                -> ambiguous           -> resultado esperado
```

Los scanners son async de extremo a extremo porque el collector realiza I/O
async. Application usa `await` directo y nunca inicia ni cierra el event loop;
esa responsabilidad pertenece al entry point. El procesamiento continúa
siendo estrictamente secuencial.

## P3 deterministic search-plan generation

La generación de planes es un caso de uso separado de Application.
`DefaultSearchPlanGenerator` implementa `ISearchPlanGenerator`, recibe
`IGameCatalog` por constructor y produce un `SearchPlanGenerationResult` con
un `SearchPlan` explícito. La estrategia actual `CANONICAL_ONLY` resuelve
targets por nombre canónico normalizado y plataforma, construye keywords
canónicas, conserva el orden y deduplica antes de aplicar el límite atómico de
consultas.

```text
External entry point
        |
        +-- Infrastructure
        |       +-- PackagedGameCatalog implements IGameCatalog
        |       +-- marketplace adapters and valuation implementations
        |
        +-- Application
                +-- DefaultSearchPlanGenerator (sync)
                |       +-- Domain: GameCatalogEntry and IGameCatalog
                |
                +-- DefaultSearchOrchestrator (async)
                        +-- existing scanners and Domain ports
```

`GameCatalogEntry` e `IGameCatalog` pertenecen a Domain.
`PackagedGameCatalog` pertenece a Infrastructure y desacopla Application del
formato JSON empaquetado. Los contratos de generación y
`DefaultSearchPlanGenerator` viven en Application. Por tanto, Application no
importa Infrastructure y la composición se realiza desde un entry point
externo.

El generator es síncrono y no ejecuta el plan. El orchestrator es async y no
genera queries. Un entry point llama primero a `generate()` y después a
`execute()`. Las métricas de generación y ejecución permanecen separadas.

La generación automática existente es determinista y no usa IA, LLM,
embeddings, fuzzy matching ni aliases de detección. El catálogo validado
contiene actualmente 50 juegos, todos PS4. `FuzzyGameDetector` aún carga el
recurso por su propio camino histórico; no ha sido migrado a `IGameCatalog`.
Esta duplicidad temporal de carga queda como limitación técnica.

## P4 operational CLI

Presentation es la capa exterior y contiene los modelos estrictos de
configuración TOML, `load_app_config`, el composition root, los renderers, el
writer JSON y los entry points `main`/`__main__`. El console script
`wallapop-arbitrage` apunta a `presentation.cli.main:main`.

```text
User / console script / python -m presentation.cli
        │
        └── Presentation
                ├── config_loader (único lector TOML)
                ├── composition (único constructor y dueño del lifecycle)
                ├── main (única frontera asyncio.run)
                ├── terminal_report
                └── json_report (informe, no persistencia histórica)
                        │
                        ├── Application use cases
                        ├── Domain ports/entities
                        └── Infrastructure adapters
```

La CLI no construye scanners directamente: `composition.py` inyecta los
adaptadores concretos y abre/cierra `WallapopPlaywrightClient`. `main.py` solo
traduce argumentos, ejecuta el generator y el orchestrator, cierra el runtime
y renderiza sus resultados. No hay scheduler, persistencia, reintentos ni
concurrencia. La configuración permanece sin I/O operativo y la salida JSON
se escribe atómicamente como informe local.

El informe operativo usa JSON `schema_version = 2` e incluye colecciones y
contadores separados para candidatos `ignored` y `ambiguous`; ninguno se
mezcla con `failures`. Antes de abrir el runtime, la CLI valida el destino JSON
evidente (padre existente, target no directorio y política de overwrite). El
writer repite la validación y conserva el reemplazo atómico. Sigue existiendo
una ventana TOCTOU entre el preflight y `os.replace()` cuando
`overwrite=False`; es un riesgo residual de filesystem, no persistencia.

La política reconoce menciones de PS5, Xbox o Nintendo solo para evitar un
routing inseguro. Eso no equivale a poder valorar esas plataformas: el recurso
productivo contiene actualmente 50 entradas, todas PS4. El soporte
multiplataforma real queda para P4.6.

El ranking de oportunidades individuales tiene un único contrato,
`IOpportunityRanker`, y una única implementación productiva,
`DefaultOpportunityRanker`. `DefaultOpportunityScanner` recibe el puerto por
inyección y delega una vez por lote. Solo se expone `OPPORTUNITY_SCORE`: primero
se aplica `BUY > MAYBE > SKIP` y después score descendente, con orden estable
en empates. `RankingResult` únicamente resume la lista ya ordenada. No se
filtran recomendaciones, no existen fallbacks y no se añadió ranking de lotes.

```python
async def main() -> None:
    result = await scanner.scan_multiple(listings)


if __name__ == "__main__":
    asyncio.run(main())
```

```text
External wiring / example
        │
        ├── Infrastructure adapters
        │       ├── WallapopPlaywrightClient
        │       ├── WallapopPriceCollector
        │       └── concrete implementations
        │
        └── Application use case
                ├── DefaultOpportunityScanner
                └── DefaultLotOpportunityScanner
                        │
                        └── Domain entities and ports
```

## Estructura del Proyecto

```
wallapop-arbitrage/
├── src/
│   ├── domain/                    # Capa de dominio
│   │   ├── entities/              # Entidades del negocio
│   │   │   ├── listing.py         # Anuncio normalizado
│   │   │   ├── game.py            # Juego identificado
│   │   │   ├── detected_game.py   # Relación Listing-Game
│   │   │   ├── game_price.py      # Precio histórico
│   │   │   └── opportunity.py     # Oportunidad de compra
│   │   ├── value_objects/         # Value Objects inmutables
│   │   │   ├── money.py
│   │   │   ├── location.py
│   │   │   └── price_range.py
│   │   └── interfaces/            # Ports (interfaces)
│   │       ├── marketplace_adapter.py
│   │       ├── game_detector.py
│   │       ├── pricing_engine.py
│   │       └── repositories.py
│   │
│   ├── application/               # Capa de aplicación
│   │   └── use_cases/
│   │       ├── scan_marketplace.py
│   │       ├── detect_games.py
│   │       ├── analyze_opportunity.py
│   │       └── get_top_opportunities.py
│   │
│   ├── infrastructure/            # Capa de infraestructura
│   │   ├── marketplaces/
│   │   │   └── wallapop/
│   │   │       ├── client.py      # Cliente HTTP Wallapop
│   │   │       └── adapter.py     # Implementa IMarketplaceAdapter
│   │   └── repositories/
│   │       └── (future DB repos)
│   │
│   └── shared/                    # Utilidades compartidas
│
├── tests/
│   ├── unit/                      # Tests unitarios
│   ├── integration/               # Tests de integración
│   └── e2e/                       # Tests end-to-end
│
├── pyproject.toml                 # Configuración del proyecto
├── .gitignore
└── README.md
```

## Entidades del Dominio

### Modelos canónicos actuales

| Concepto | Responsabilidad | Definición canónica |
|---|---|---|
| `CandidateListing` | Anuncio que se considera comprar; puede ser un lote | `domain/entities/candidate_listing.py` |
| `ComparableListing` | Observación individual aceptada para estimar mercado | `domain/entities/comparable_listing.py` |
| `ComparableFilterInput` | Payload previo a que el filtro acepte o rechace un comparable | `domain/interfaces/comparable_filter.py` |
| `ListingText` | Título y descripción que recibe `GameDetector` | `domain/interfaces/game_detector.py` |
| `DetectedGame` | Resultado compartido de detección | `domain/entities/detected_game.py` |
| `Platform` | Plataforma compartida por detección y valoración | `domain/entities/detected_game.py` |
| `DetectionMethod` | Método con el que se produjo una detección | `domain/entities/detected_game.py` |
| `GameValuation` | Valoración económica de un juego detectado | `domain/entities/game_valuation.py` |

Estos conceptos comparten algunos campos, pero no son intercambiables. El
`ComparableFilterInput` de `comparable_filter.py` es un payload exclusivo de ese
puerto, previo a que un anuncio sea aceptado como `ComparableListing`. Los
diccionarios devueltos por `IMarketplaceSearch` continúan siendo datos crudos
externos, no un DTO general ni una entidad de dominio.

### Listing (Anuncio)
Representa un anuncio normalizado de cualquier marketplace.

**Propiedades:**
- `id`: ListingId
- `external_id`: ID del marketplace original
- `marketplace`: Tipo de marketplace (WALLAPOP, VINTED, etc.)
- `title`, `description`: Texto del anuncio
- `price`: Money (cantidad + moneda)
- `location`: Ubicación
- `images`: Lista de URLs
- `published_at`, `discovered_at`: Timestamps
- `status`: Estado del anuncio (ACTIVE, SOLD, REMOVED)

### Game (Juego)
Representa un videojuego único en el catálogo.

**Propiedades:**
- `id`: GameId
- `canonical_name`: Nombre normalizado
- `platform`: Plataforma (PS4, XBOX_ONE, SWITCH, etc.)
- `region`: Región (PAL, NTSC_U, etc.)
- `aliases`: Nombres alternativos
- `metadata`: Información adicional

### DetectedGame
Relación entre un Listing y los Games detectados en él.

**Propiedades:**
- `listing_id`, `game_id`: Referencias
- `confidence`: Nivel de confianza (0.0 - 1.0)
- `detection_method`: Método usado (TITLE_MATCH, IMAGE_OCR, etc.)
- `condition`: Estado (SEALED, COMPLETE, LOOSE, etc.)
- `quantity`: Cantidad detectada

### GamePrice
Snapshot del precio estimado de mercado de un juego.

**Propiedades:**
- `game_id`: Referencia al juego
- `estimated_price`: Precio estimado
- `price_range`: Rango (min, max, median, percentiles)
- `sample_size`: Número de anuncios analizados
- `calculated_at`: Timestamp del cálculo
- `validity_period`: Tiempo de validez

### Opportunity
Análisis de rentabilidad de un anuncio.

**Propiedades:**
- `listing_id`: Referencia al anuncio
- `detected_games`: Juegos detectados
- `reference_market_value`: Valor total estimado
- `expected_profit`: Beneficio esperado
- `profit_margin`, `roi`: Métricas
- `confidence_score`: Nivel de confianza
- `status`: Estado (NEW, REVIEWED, PURCHASED, etc.)

## Interfaces (Ports)

### IMarketplaceAdapter
Obtiene anuncios de un marketplace externo.

```python
def search(query: SearchQuery) -> Iterator[RawListing]
def get_listing(external_id: str) -> RawListing
def get_marketplace_type() -> MarketplaceType
```

### IGameDetector
Detecta juegos en un anuncio.

```python
def detect_games(listing: Listing) -> list[DetectedGame]
```

### IPricingEngine
Calcula precios de mercado.

```python
def calculate_price(game: Game, condition: Condition) -> GamePrice
def get_latest_price(game: Game, condition: Condition) -> GamePrice | None
```

### IRepository<T>
Persistencia genérica.

```python
def save(entity: T) -> EntityId
def get(entity_id: EntityId) -> T | None
def find(criteria: Criteria) -> list[T]
```

## Flujo de Datos Principal

```
1. ScanMarketplaceUseCase
   Marketplace API → RawListing → Listing normalizado → DB

2. DetectGamesInListingUseCase
   Listing → IGameDetector → DetectedGame → DB

3. AnalyzeOpportunityUseCase
   DetectedGame + IPricingEngine → Opportunity → DB

4. GetTopOpportunitiesUseCase
   Query DB → Ranking de Opportunities
```

## Estrategia de Implementación

### Fase 1: Investigación ✅
- Validar API de Wallapop
- Documentar estructura de datos

### Fase 2: Estructura Base ✅ (ACTUAL)
- Configurar proyecto (uv, pyproject.toml)
- Crear estructura de carpetas
- Configurar herramientas (ruff, mypy, pytest)

### Fase 3: Domain Layer
- Implementar entidades
- Implementar value objects
- Definir interfaces

### Fase 4: Wallapop Adapter
- Implementar WallapopClient
- Implementar WallapopAdapter
- Tests de integración

### Fase 5: Casos de Uso MVP
- ScanMarketplaceUseCase
- Persistencia básica (JSON/SQLite)
- Verificación end-to-end

### Fase 6+: Expansión
- Detección de juegos
- Motor de valoración
- Análisis de oportunidades
- Nuevos marketplaces

## Decisiones Técnicas

### Tecnologías
- **Python 3.11+**: Lenguaje base
- **uv**: Gestor de paquetes
- **httpx**: Cliente HTTP async
- **pydantic**: Validación y serialización
- **pytest**: Testing framework
- **ruff**: Linter y formatter
- **mypy**: Type checking

### Patrones de Diseño
- **Dependency Injection**: Inyección de dependencias en casos de uso
- **Repository Pattern**: Abstracción de persistencia
- **Strategy Pattern**: Múltiples implementaciones de detectores/pricers
- **Adapter Pattern**: Adaptadores de marketplace

### Testing
- **Unit tests**: Lógica de dominio aislada
- **Integration tests**: Adaptadores con servicios externos
- **E2E tests**: Flujo completo de casos de uso

## Extensibilidad

### Añadir un nuevo marketplace

1. Crear `infrastructure/marketplaces/{marketplace}/`
2. Implementar `{Marketplace}Client` (HTTP/scraping)
3. Implementar `{Marketplace}Adapter` (IMarketplaceAdapter)
4. Escribir tests de integración
5. **No modificar el dominio**

### Añadir un nuevo detector de juegos

1. Crear clase que implemente `IGameDetector`
2. Registrar en configuración
3. Opcionalmente combinar con otros detectores

### Añadir un nuevo pricing engine

1. Crear clase que implemente `IPricingEngine`
2. Configurar como implementación por defecto o alternativa

## Notas Importantes

- El dominio **nunca** debe importar de infrastructure
- Cada marketplace devuelve `Listing` normalizado (mismo formato)
- La IA es siempre opcional, no obligatoria
- Priorizar almacenamiento de históricos sobre análisis en tiempo real
- La arquitectura debe facilitar testing desde el día 1
# P1.6 analysis flow

Both application scanners create `ListingText` from a candidate and invoke the
domain `IGameDetector`. The individual use case accepts exactly one detected
game; the lot use case accepts and stably deduplicates multiple detected games.
Neither use case treats the candidate itself as a market comparable.

`DefaultPriceDatasetBuilder` is the single production boundary for comparable
publication uniqueness. After application-level candidate exclusion and
currency selection, it validates all inputs and stably retains the first
`ComparableListing` for each `(DetectedGame.platform, listing_id)`. The policy
is local to a dataset build and never mutates the raw execution-scoped cache.

`WallapopPriceCollector` is the infrastructure boundary for comparable game
identity. Before returning a `ComparableListing`, it requires exact equality
of both canonical name and `Platform` with the requested `DetectedGame`.
Application does not duplicate this filter, and the builder remains concerned
with validation and publication deduplication rather than platform matching.
Whole-search technical exceptions propagate unchanged to Application, while
ordinary failures processing one raw listing remain warning-and-continue.
Thus an empty collection means a completed search with no valid comparables;
it is not the representation of a source failure.

At the Playwright gateway boundary, the defensive contract requires the full
`data.section.items` shape. Only a present empty list represents an empty page.
Missing containers, wrong types, invalid pagination token types, or a malformed
later page raise `WallapopSearchResponseError`. The collector propagates it,
scanners structure it as a price-collection failure, and no partial collection
enters the cache. This is an internal contract based on observed payloads, not
an official schema guarantee; it adds neither retry nor fallback.

The batch opportunity use case isolates synchronous game-detection exceptions
at the per-candidate iteration boundary. Such a failure becomes an application
`FailureInfo` and cannot touch collection, cache, valuation or ranking inputs
for that candidate. This application concern is not duplicated in Domain,
Infrastructure or the lot-scanning use case.

The individual arbitrage detector owns its decision thresholds. Its absolute
net-profit configuration is a `Mapping[str, Decimal]` resolved from
`EconomicBreakdown.currency`; omission or `None` means only EUR 10.0, while an
explicit mapping replaces the default and zero remains zero. Missing currencies
are configuration errors—there is no EUR fallback or FX. Dependency injection
supplies the detector to Application unchanged. Margin and confidence rules and
the lot analyzer remain separate.

The lot analyzer independently owns its own
`min_net_profit_by_currency: Mapping[str, Decimal]`. It also resolves against
`EconomicBreakdown.currency`, defaults only to EUR 10.0 for `None`, and rejects
unconfigured currencies without EUR fallback or FX. Application injects the
configured analyzer unchanged; the lot scanner contains no threshold selection.
Coverage and lot recommendation rules are unaffected.

`ResaleEconomicPolicy` separates global dimensionless rates from absolute
currency configuration. Each canonical currency maps to one frozen
`ResaleAbsoluteCosts` bundle. The mapping is defensively copied and immutable.

`LotOpportunity` is the immutable-snapshot boundary for the collection of
successful lot valuations. Application and analyzer code may use mutable local
lists, while the domain entity stores an ordered tuple created by its factory.
`LotScanResult` retains its existing list contract; the two collections are not
aliased. This changes no dependency direction or economic calculation.

The Application lot-scanner contract separates local valuation failures from
aggregate analysis failures. `GameValuationFailure` remains game-scoped;
`LotScanResult.analysis_failure: FailureInfo | None` reports an ordinary
analyzer exception at `PipelineStage.LOT_ANALYSIS`. The domain analyzer does
not depend on scanner results and is not modified by this adaptation.
`neutral()` means EUR only; callers use `neutral("USD")`, `neutral("GBP")`, or
an explicit multimonetary mapping. Missing currency fails without zero/EUR
fallback or FX.

Publication identifiers are opaque strings validated by the shared Domain
function `validate_listing_id`. Domain never strips, changes case, parses a
number, or removes leading zeroes. Wallapop infrastructure reads the real `id`
field from the API payload, trims surrounding whitespace for strings, converts
confirmed integer payload IDs to strings, and rejects missing, empty, boolean,
float, or otherwise unsupported values. No URL or content-derived fallback is
used.
There is no automatic router between these use cases. Physical quantities
such as "2 copies of GTA V" are not modeled; canonical duplicates represent
one valuation identity.
# P1.7 economic policy

`domain/entities/resale_economics.py` is the single canonical definition of
`ResaleEconomicPolicy` and `EconomicBreakdown`. Infrastructure detectors and
analyzers consume that breakdown as the single financial source of truth.
Opportunity entities store the breakdown once and delegate their canonical
financial properties to it; they do not persist parallel profit, margin, ROI,
discount, or break-even copies. Infrastructure detectors and analyzers require
the policy through constructor injection. Application
scanners neither construct nor configure it.

## P1.12 single-currency boundary

Every monetary pipeline carries one canonical three-letter uppercase ASCII
currency code as `str`. Infrastructure normalizes external codes; Domain rejects
non-canonical codes. Foreign-currency comparables are removed before dataset
construction, while `PriceDataset` strictly rejects mixed inputs. Statistics,
outliers, estimates and economic breakdowns preserve the currency. There is no
Currency enum, Money, EUR fallback, FX conversion, symbol inference or rounding.

## P1.13 conservative zero-IQR policy

The single infrastructure Tukey implementation abstains from removal when the
interquartile range is exactly `Decimal("0")`. It copies the observation list,
preserves order, Decimal and currency, and exposes observed min/max as effective
bounds. No alternative outlier algorithm or fallback is introduced.
