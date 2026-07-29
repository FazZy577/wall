# SearchPlanGenerator

`DefaultSearchPlanGenerator` es el caso de uso síncrono de Application que
transforma una selección explícita de juegos del catálogo en un `SearchPlan`
validado. Existe generación automática determinista de consultas canónicas,
sin IA.

## Responsabilidades

El flujo es:

```text
GameSearchTarget
        ↓
SearchPlanGenerationRequest
        ↓
DefaultSearchPlanGenerator
        ↓
IGameCatalog
        ↓
SearchPlanGenerationResult
        ↓
SearchPlan
        ↓
DefaultSearchOrchestrator
```

El generator:

- valida la solicitud mediante sus contratos públicos;
- resuelve cada target contra `IGameCatalog`;
- construye una consulta canónica por target resuelto;
- conserva el orden de entrada;
- elimina consultas duplicadas conservando la primera;
- aplica `max_queries` después de deduplicar;
- devuelve el plan y métricas exclusivas de generación.

No ejecuta búsquedas, no llama al orquestador, no detecta juegos en anuncios,
no recoge comparables, no valora oportunidades y no controla el event loop.
Tampoco persiste resultados, programa ejecuciones ni aplica ranking.

## Contratos

### GameSearchTarget

`GameSearchTarget` identifica el juego solicitado mediante:

- `canonical_name: str`;
- `platform: Platform`.

El nombre se recorta y debe ser no vacío. La plataforma debe ser un miembro de
`Platform` distinto de `UNKNOWN`. El target no es una query libre ni un alias
de detección.

### SearchPlanGenerationStrategy

La única estrategia disponible es `CANONICAL_ONLY`. No existe todavía
`CANONICAL_AND_ALIASES`.

### SearchPlanGenerationRequest

La solicitud contiene:

- `targets: tuple[GameSearchTarget, ...]`;
- `latitude: float`;
- `longitude: float`;
- `max_results: int`;
- `max_queries: int`;
- `strategy`, con `CANONICAL_ONLY` como valor actual.

Las coordenadas deben ser finitas y pertenecer a sus rangos geográficos.
`max_results` y `max_queries` deben ser enteros positivos. Una colección vacía
de targets es válida y genera un plan vacío.

### SearchPlanGenerationResult

El resultado contiene:

- `plan: SearchPlan`;
- `targets_received`;
- `queries_generated`;
- `duplicate_queries_removed`.

Estas métricas describen únicamente la generación. No duplican los contadores
de consultas ejecutadas, candidatos o fallos de `SearchOrchestrationResult`.

### ISearchPlanGenerator y DefaultSearchPlanGenerator

`ISearchPlanGenerator` es el puerto de entrada de Application. Su método
`generate(request)` es síncrono. `DefaultSearchPlanGenerator` recibe por
constructor un `IGameCatalog`; no conoce JSON ni implementaciones concretas de
Infrastructure y no conserva estado entre llamadas.

## Catálogo canónico

`GameCatalogEntry` es la entidad de Domain que contiene:

- nombre canónico;
- plataforma;
- `detection_aliases`.

`IGameCatalog` expone un snapshot inmutable de entradas. Su adapter actual,
`PackagedGameCatalog`, vive en Infrastructure, carga y valida el recurso
empaquetado una vez durante su construcción y devuelve una tupla.

El recurso actual contiene 50 entradas y todas pertenecen a PS4. Aunque
`Platform` puede representar otras plataformas, el catálogo empaquetado no
contiene actualmente juegos de PS5, Xbox ni Nintendo Switch.

Los aliases del recurso son `detection_aliases`: sirven para detectar juegos
en texto de anuncios y no están certificados como términos seguros de
búsqueda. `CANONICAL_ONLY` no los utiliza como keywords.

No existen IDs estables de juegos. La identidad provisional para resolver
targets es el nombre canónico normalizado junto con la plataforma.

## Resolución, keywords y deduplicación

Para resolver identidades, el nombre se normaliza mediante `strip`, colapso de
espacios y `casefold`. No hay fuzzy matching, embeddings ni resolución por
aliases.

Las keywords se construyen con el nombre canónico exacto de la entrada y el
valor de plataforma, separados por un espacio. El generator no inventa
aliases, variantes ni términos adicionales.

La clave de deduplicación de queries contiene:

- keywords normalizadas con `strip`, colapso de espacios y `casefold`;
- `latitude`;
- `longitude`;
- `max_results`.

No se redondean coordenadas. Gana la primera aparición y el orden resultante es
determinista.

## Límites, errores y atomicidad

`max_queries` se comprueba después de deduplicar. Si el límite se supera, no se
trunca el plan.

- `UnknownGameSearchTargetError`: algún target no existe en el catálogo.
- `SearchPlanLimitExceededError`: las consultas únicas superan `max_queries`.
- `SearchPlanGenerationError`: catálogo inválido, identidad duplicada,
  estrategia no soportada o incumplimiento defensivo del contrato.

La operación es atómica: ante cualquiera de estos errores no se devuelve un
plan parcial.

## Sincronía y composición

El generator es síncrono porque lee un snapshot de catálogo ya cargado y solo
construye objetos. El orchestrator es async porque ejecuta puertos con I/O.
Ninguno llama al otro: un entry point externo compone ambos explícitamente.

```python
generation = generator.generate(request)
execution = await orchestrator.execute(generation.plan)
```

El generator no abre ni cierra clientes y el orchestrator conserva su
responsabilidad actual de ejecutar un plan, no de generarlo.

## Ausencia de IA

La generación automática actual:

- es determinista;
- no utiliza modelos de IA ni LLM;
- no utiliza embeddings;
- no utiliza fuzzy matching para resolver targets;
- no inventa aliases;
- no usa `detection_aliases` como search keywords.

## Ejemplo offline y tests

El ejemplo `examples/search_plan_generator_example.py` compone el catálogo, el
generator y el orchestrator con los scanners y componentes productivos. Solo
sustituye la frontera externa por un `IMarketplaceSearch` manual en memoria:

```powershell
py examples/search_plan_generator_example.py
```

No usa red ni Playwright y no escribe archivos. El smoke test
`tests/integration/test_search_plan_generator_example.py` comprueba sus
secciones y métricas estables. La integración de comportamiento completa vive
en `tests/integration/test_search_plan_generator_pipeline.py`; los contratos y
casos límite tienen pruebas unitarias.

## Limitaciones actuales

No están implementados:

- aliases seguros de búsqueda;
- `CANONICAL_AND_ALIASES`;
- selección automática de todo el catálogo;
- generación mediante IA;
- IDs estables de juegos;
- persistencia e histórico;
- scheduler, reintentos o concurrencia;
- notificaciones;
- CLI operativa, API o dashboard;
- demanda, liquidez o conversión de divisas.

`FuzzyGameDetector` todavía carga el mismo recurso empaquetado por su camino
existente en lugar de recibir `IGameCatalog`. Esta duplicidad temporal de carga
no altera la separación: el generator usa `IGameCatalog` y el detector conserva
su implementación actual.
