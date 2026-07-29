# SearchOrchestrator

`DefaultSearchOrchestrator` es el caso de uso de Application que coordina una
ejecución explícita de búsquedas de candidatos. No es un cliente de Wallapop:
recibe sus puertos por inyección y conserva separados los resultados del
scanner individual y del scanner de lotes.

## Responsabilidades

Una ejecución sigue este flujo:

```text
SearchPlan
    ↓
ICandidateSearch
    ↓
CandidateListing
    ↓
deduplicación
    ↓
GameDetector
    ├── 0 juegos → routing failure
    ├── 1 juego  → OpportunityScanner
    └── varios   → LotOpportunityScanner
```

El orquestador:

- deduplica consultas equivalentes conservando la primera aparición;
- ejecuta las consultas únicas secuencialmente;
- conserva fallos técnicos de consultas y fallos de conversión por elemento;
- deduplica candidatos globalmente por `CandidateListing.listing_id`;
- detecta juegos una sola vez por candidato único;
- envía todos los candidatos individuales en una única llamada batch;
- procesa los lotes secuencialmente y mantiene sus `LotScanResult` separados;
- devuelve contadores, resultados parciales y fallos en
  `SearchOrchestrationResult`.

No calcula estadísticas, recopila comparables, estima precios, elimina
outliers ni aplica reglas económicas. Tampoco implementa ranking: el ranking
individual sigue perteneciendo a `DefaultOpportunityScanner` y los lotes
conservan el contrato separado de `DefaultLotOpportunityScanner`.

## SearchPlan y deduplicación

`SearchPlan` contiene una tupla ordenada de `SearchQuery`. Cada consulta
incluye `keywords`, `latitude`, `longitude` y `max_results`; el contrato valida
texto no vacío, coordenadas finitas y un límite positivo.

El plan puede construirse manualmente o generarse de forma determinista con
`DefaultSearchPlanGenerator`. El generator síncrono resuelve targets del
catálogo y devuelve un plan explícito; después, un entry point entrega ese plan
al orchestrator async. Las responsabilidades y métricas siguen separadas: el
orquestador no genera queries. Véase
[`SEARCH_PLAN_GENERATOR.md`](SEARCH_PLAN_GENERATOR.md).

La clave local de deduplicación normaliza solo `keywords` con `strip`,
colapso de espacios y `casefold`, y conserva sin redondear las coordenadas y
`max_results`. La primera consulta gana y las consultas duplicadas no se
reintentan en esa ejecución. `total_queries` cuenta la entrada original;
`executed_queries` y `duplicate_queries` describen el resultado de esta
deduplicación.

Los candidatos se deduplican después de completar las búsquedas. El primer
`listing_id` observado gana y el orden estable se conserva. No se fusionan
payloads, títulos ni `raw_listing`.

## Fallos y resultados parciales

Una búsqueda que devuelve `CandidateSearchResult` vacío es un éxito vacío.
Una excepción técnica de la búsqueda se registra como `SearchQueryFailure` y
no borra los éxitos de otras consultas. Las excepciones de detección y de
scanners se aíslan según candidato o batch. La cancelación async y las
excepciones de salida del proceso no se convierten en fallos ordinarios.

`SearchOrchestrationResult` mantiene tres colecciones de fallos:
`query_failures`, `item_failures` y `routing_failures`. También mantiene
`individual_result: ScanResult | None` y `lot_results: tuple[LotScanResult,
...]`; no mezcla oportunidades individuales y de lotes en una lista común.

## Lifecycle y arquitectura

Application depende únicamente de Domain y de los puertos de Application. La
implementación concreta de Wallapop vive en Infrastructure:

```text
External wiring / example
        │
        ├── Infrastructure adapters
        │       ├── WallapopPlaywrightClient
        │       ├── WallapopCandidateSearchAdapter
        │       └── WallapopPriceCollector
        │
        └── Application use case
                └── DefaultSearchOrchestrator
                        ├── DefaultOpportunityScanner
                        └── DefaultLotOpportunityScanner
                                │
                                └── Domain entities and ports
```

El orquestador no crea ni cierra clientes, no abre Playwright, no controla el
event loop y no usa `asyncio.run()`. El entry point externo puede compartir una
misma sesión `WallapopPlaywrightClient` entre el adapter de candidatos y el
collector, y cerrarla mediante `async with`. Las búsquedas del orquestador son
secuenciales; no hay concurrencia ni reintentos.

## Ejecución offline

`examples/search_orchestrator_example.py` conecta las implementaciones
productivas con un `IMarketplaceSearch` en memoria. Incluye una consulta
individual, una consulta de lote, una consulta semánticamente duplicada, un
candidato repetido y comparables deterministas. Se ejecuta sin red:

```powershell
py examples/search_orchestrator_example.py
```

El informe muestra contadores de consultas y candidatos, oportunidades
individuales, resultados de lote, fallos y tiempo de procesamiento. La prueba
`tests/integration/test_search_orchestrator_example.py` comprueba únicamente
que el ejemplo termina correctamente y expone sus secciones principales.

## Smoke test live

`tests/e2e/test_search_orchestrator_live.py` es un smoke test opt-in con una
sola consulta (`gta 5 ps4`), como máximo un candidato, hasta diez comparables
por valoración, una página y procesamiento secuencial. Reutiliza una instancia
de `WallapopPlaywrightClient` entre el adapter y el collector; el lifecycle
continúa fuera del orquestador.

No se ejecuta sin:

```text
RUN_LIVE_WALLAPOP_TESTS=1
```

En PowerShell:

```powershell
$env:RUN_LIVE_WALLAPOP_TESTS = "1"
py -m uv run pytest tests/e2e/test_search_orchestrator_live.py -v
Remove-Item Env:RUN_LIVE_WALLAPOP_TESTS
```

El smoke test no exige precios exactos ni una recomendación concreta. Comprueba
invariantes estables: contadores, coherencia del routing, tipos monetarios
`Decimal`, moneda no vacía, endpoint capturado y cierre del browser. Una
respuesta estructuralmente inválida o un timeout sigue siendo un error técnico;
no se convierte en una búsqueda vacía.

## Limitaciones actuales

El caso de uso no genera queries, aliases ni variantes. Un caso de uso
separado puede generar automáticamente consultas canónicas deterministas, pero
todavía no existen aliases seguros de búsqueda ni generación mediante IA. El
orquestador no persiste histórico, no ofrece CLI/API/dashboard, no implementa
FX ni demanda/liquidez y no automatiza ejecuciones periódicas. La
disponibilidad del smoke test live depende de Wallapop, Chromium y la
estructura pública vigente de su endpoint.
