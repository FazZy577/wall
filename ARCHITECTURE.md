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

Los scanners son async de extremo a extremo porque el collector realiza I/O
async. Application usa `await` directo y nunca inicia ni cierra el event loop;
esa responsabilidad pertenece al entry point. El procesamiento continúa
siendo estrictamente secuencial.

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
