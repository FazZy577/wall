# Lot Opportunity Scanner

The scanner preserves Decimal prices through collection, datasets, statistics,
estimation and lot economics. Only final dimensionless ratios used to construct
`opportunity_score` are explicitly converted to float.

**Contract and execution results:**
`application.interfaces.lot_opportunity_scanner`

**Use-case implementation:**
`application.use_cases.default_lot_opportunity_scanner`

## Complete comparable game identity

Before each dataset is built, `PriceCollector` guarantees that every result
has exactly the requested canonical name and platform. A PS5 result cannot
enter a PS4 dataset, or vice versa. There is no cross-generation compatibility,
platform wildcard or relabelling. Currency is validated separately, and stable
deduplication by `(platform, listing_id)` remains the builder's responsibility.

El scanner pertenece a Application: coordina puertos inyectados y entidades
del dominio, sin importar ni instanciar implementaciones de Infrastructure.

Su API pública es async porque propaga el I/O async de `PriceCollector`. Cada
juego continúa procesándose secuencialmente con `await`; no se usan tareas,
`gather` ni concurrencia, y Application no gestiona el event loop.

## Responsabilidad del scanner

`LotOpportunityScanner` orquesta el pipeline de valoración de un lote ya detectado. Recibe un `CandidateListing` con su lista de `DetectedGame` y procesa cada juego por separado.

El scanner:

- recorre `listing.detected_games` sin deduplicar;
- busca comparables para cada juego mediante `PriceCollector`;
- construye un `PriceDataset` solo con anuncios comparables;
- calcula estadísticas iniciales;
- elimina outliers;
- recalcula estadísticas sobre el dataset limpio;
- estima el precio de mercado;
- crea un `GameValuation` por juego valorado;
- registra fallos por juego sin detener todo el lote;
- delega el análisis final en `LotOpportunityAnalyzer`.

El scanner no decide `BUY`, `MAYBE` o `SKIP` y no calcula `opportunity_score`.

## Responsabilidad del analyzer

`LotOpportunityAnalyzer` recibe:

- el `CandidateListing`;
- las `GameValuation` obtenidas;
- `total_detected_games`.

El analyzer no busca comparables, no construye datasets, no calcula estadísticas de mercado y no conoce Wallapop ni Playwright.

Su responsabilidad es calcular las métricas agregadas del lote y decidir:

- `recommendation`;
- `reason`;
- `opportunity_score`.

También compara `len(game_valuations)` con `total_detected_games` para saber si la valoración está completa.

## Pipeline por juego

```text
DetectedGame
    ↓
PriceCollector
    ↓
PriceDatasetBuilder
    ↓
PriceStatistics
    ↓
OutlierRemoval
    ↓
PriceStatistics recalculadas
    ↓
MarketPriceEstimator
    ↓
GameValuation
```

Cada juego se valora de forma independiente. Un fallo en un juego se guarda como `GameValuationFailure` con la etapa exacta donde ocurrió.

Una búsqueda externa completada sin resultados produce el fallo funcional de
no comparables en `PRICE_COLLECTION`, sin `error_message`. Una excepción
técnica propagada por `WallapopPriceCollector` produce un fallo distinto en la
misma etapa con el mensaje original; los juegos posteriores continúan. Los
errores aislados por raw listing mantienen su warning best-effort.

En el gateway Playwright solo `data.section.items=[]` representa una página
vacía válida. Una estructura nested ausente o incorrecta, también en una página
posterior, se propaga como `WallapopSearchResponseError` y se representa como
`GameValuationFailure` de `PRICE_COLLECTION`. No se conservan parciales y no se
usa `analysis_failure`, reservado al analyzer agregado.

## Tratamiento de fallos parciales

Un lote puede contener juegos que no se puedan valorar por falta de comparables, dataset vacío, errores estadísticos, errores de estimación o errores inesperados del pipeline.

El scanner conserva:

- `game_valuations`: juegos valorados correctamente;
- `failures`: juegos que fallaron y etapa del fallo;
- `total_detected_games`;
- `successfully_valued_games`;
- `failed_games`;
- `is_complete`.

Después, el analyzer produce igualmente un `LotOpportunity` cuando hay juegos detectados, pero marca el lote como incompleto si no se valoraron todos.

## Por qué una valoración incompleta nunca puede ser BUY

Si falta valorar algún juego, el valor total del lote puede estar subestimado o el texto puede incluir títulos ambiguos. Para evitar compras con información incompleta, una valoración parcial nunca puede producir `BUY`.

La regla inicial es conservadora:

- valoración completa: puede ser `BUY`, `MAYBE` o `SKIP` según beneficio, margen y confianza;
- valoración incompleta con beneficio positivo: como máximo `MAYBE`;
- valoración incompleta sin beneficio positivo: `SKIP`.

## Por qué CandidateListing no entra en PriceDataset

`CandidateListing` representa el anuncio que queremos comprar. `ComparableListing` representa anuncios externos usados como referencia de mercado.

El precio del candidato no debe entrar en `PriceDataset` porque contaminaría la estimación del mercado. Para valorar un lote de 35 EUR, el dataset de cada juego debe construirse solo con comparables de ese juego, no con el precio del lote ni con el anuncio candidato.

## Diferencia con OpportunityScanner

`OpportunityScanner` analiza oportunidades individuales. Procesa un anuncio de un solo juego, estima su valor de mercado y detecta la oportunidad individual.

`LotOpportunityScanner` analiza lotes. No compara el precio del lote contra un único juego, sino contra la suma de las valoraciones individuales de todos los juegos detectados.

La separación queda así:

- `OpportunityScanner`: candidato individual;
- `LotOpportunityScanner`: candidato lote;
- `OpportunityRanker`: ordenación posterior de oportunidades individuales;
- `LotOpportunityAnalyzer`: reglas agregadas del lote.

## Limitación actual sobre cantidades duplicadas

El scanner procesa cada entrada de `detected_games`. No deduplica automáticamente juegos repetidos.

Esto permite representar dos copias del mismo juego si aparecen como dos `DetectedGame`, pero el sistema todavía no interpreta cantidades explícitas del texto como `2x GTA V`. Esa normalización de cantidades queda pendiente para una capa futura de detección/enriquecimiento del candidato.

## Futura integración con SearchOrchestrator

El `SearchOrchestrator` futuro decidirá si cada anuncio detectado debe ir al pipeline individual o al pipeline de lotes.

```text
SearchOrchestrator futuro
        │
        ├── candidato individual
        │       ↓
        │   OpportunityScanner
        │
        └── lote
                ↓
        LotOpportunityScanner
                ↓
        LotOpportunityAnalyzer
```

El `SearchOrchestrator` no está implementado todavía. El pipeline de lotes queda preparado para recibir `CandidateListing` ya construidos y enriquecidos con `detected_games`.

## Explicabilidad

`LotScanResult.explain()` devuelve una explicación determinista con:

- lote;
- juegos detectados;
- juegos valorados;
- juegos fallidos;
- valoración individual;
- valor total de mercado;
- precio del lote;
- beneficio estimado;
- margen;
- ROI;
- confianza agregada;
- completion ratio;
- opportunity score;
- recommendation;
- reason.
# P1.6: detector-owned lot contents

The lot scanner receives `IGameDetector` by constructor injection and detects
games from `ListingText(title, description)`. `CandidateListing` no longer
stores detected games. Detector results are deduplicated in stable order by
normalized `canonical_name` plus `Platform.value`, then valued sequentially.

A zero-game result produces a `GAME_DETECTION` failure carrying the candidate
`listing_id` and does not call the collector or analyzer. Before each dataset
is built, a comparable with the candidate's own `listing_id` is excluded.
# P1.7: aggregate net economics

The lot analyzer applies the same injected `ResaleEconomicPolicy` once to the
successfully valued games. Purchase price and acquisition overhead are charged
once per lot; quick-sale discount and fixed selling cost apply once per valued
item. Unvalued games add neither invented revenue nor selling cost, while still
affecting the existing coverage rules. `LotOpportunity.economic_breakdown`
preserves the complete calculation.

## P1.12 comparable currencies

For each game, the scanner excludes the candidate ID and then selects only raw
comparables matching the lot currency. No compatible comparables produces a
`GameValuationFailure` naming that currency; other games continue. Builder and
analyzer provide strict defenses against mixed currencies.

The injected lot analyzer owns an independent
`min_net_profit_by_currency: Mapping[str, Decimal]` configuration. `None`
configures only historical EUR 10.0; explicit mappings replace that default,
`{}` configures nothing, and explicit zero remains zero. The analyzer resolves
the threshold from `EconomicBreakdown.currency`, without EUR fallback or FX.
USD/GBP require explicit entries. Mixed platforms remain supported when the lot
currency is homogeneous. Coverage and recommendation rules are unchanged.

The scanner does not reconstruct or select thresholds. An ordinary analyzer
exception is still logged and produces `opportunity=None`, but is also exposed
as `LotScanResult.analysis_failure` using the canonical `FailureInfo` with
`PipelineStage.LOT_ANALYSIS`.

The injected `ResaleEconomicPolicy` resolves all three absolute costs together
from `absolute_costs_by_currency` using the homogeneous lot currency. The
bundle has no fallback and no FX. Per-item costs and one-time overhead retain
their formulas. A missing bundle preserves completed valuations and produces a
structured `analysis_failure` alongside `opportunity=None`.

## P1.22 opportunity snapshot boundary

The scanner and analyzer continue accumulating successful valuations in local
lists. `LotOpportunity.from_valuations()` snapshots that collection once as an
ordered `tuple[GameValuation, ...]`. Consequently, mutating
`LotScanResult.game_valuations` after the scan does not alter the opportunity's
valuation collection or any derived value. Duplicates and mixed-platform order
are preserved; no deep copy, sorting or deduplication is introduced.

## P1.23 structured aggregate-analysis failures

`LotScanResult.failures` remains a list of `GameValuationFailure` values tied
to individual games. The separate optional `analysis_failure` contains at most
one canonical `FailureInfo` for an exception raised by the aggregate analyzer.
Its listing ID is the candidate lot, its stage is `LOT_ANALYSIS`, and its error
message preserves the exception type and message without embedding a traceback.

Game-level and aggregate failures can coexist. Completed valuations are not
discarded. A valid BUY, MAYBE or SKIP opportunity always has
`analysis_failure=None`; SKIP is a business result, not a technical failure.
The analyzer continues to raise and the scanner adapts ordinary `Exception`
instances while preserving the existing operational log. `BaseException`,
including `KeyboardInterrupt` and `SystemExit`, is not captured.

## P1.14 unique comparables per game dataset

For each detected game, candidate exclusion and lot-currency filtering still
occur before dataset construction. The shared `DefaultPriceDatasetBuilder`
then preserves the first occurrence of each `(platform, listing_id)` and
discards later valid duplicates without mutating collector output. Each game
gets an independent seen set, so there is no global deduplication between game
valuations. Coverage and `GameValuation.sample_size` use the resulting unique
market observations.

Each comparable entering the lot pipeline has a non-empty canonical
`listing_id`. Results without a real Wallapop ID are discarded at the adapter
boundary, so they cannot create a misleading `GameValuation`; other canonical
comparables and games continue under the existing partial-failure rules.
