# Lot Opportunity Scanner

The scanner preserves Decimal prices through collection, datasets, statistics,
estimation and lot economics. Only final dimensionless ratios used to construct
`opportunity_score` are explicitly converted to float.

**Contract and execution results:**
`application.interfaces.lot_opportunity_scanner`

**Use-case implementation:**
`application.use_cases.default_lot_opportunity_scanner`

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
