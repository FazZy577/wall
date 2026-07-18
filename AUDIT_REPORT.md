# AUDIT_REPORT.md — Auditoría del Repositorio wallapop-arbitrage

**Fecha de auditoría:** 2026-07-18
**Auditor:** Software Architect Senior / Auditor de código
**Alcance:** Estado actual del repositorio, sin implementar ni refactorizar.

---

## 1. Executive Summary

El proyecto `wallapop-arbitrage` es una plataforma Python para detectar oportunidades de arbitraje en marketplaces de segunda mano, comenzando por Wallapop. La arquitectura sigue principios de Clean Architecture con capas Domain / Application / Infrastructure.

**Hallazgo principal:** El pipeline de dominio está implementado y probado con mocks, pero **no existe un `SearchOrchestrator` ni un cliente Playwright/Wallapop real funcional**. El `WallapopClient` actual apunta al endpoint `/api/v3/general/search`, que devuelve 403, mientras que las pruebas manuales con Playwright demuestran que el endpoint real es `/api/v3/search/section`. Esto bloquea cualquier ejecución real del pipeline.

**Resumen de comprobaciones:**

| Métrica | Valor |
|---------|-------|
| Tests totales | 346 passed |
| Tests fallidos | 0 |
| Warnings | 0 (tests), 55 errores de lint |
| Cobertura total | 95% |
| Errores de lint (ruff) | 55 (49 auto-fixables) |
| Errores de tipos (mypy) | 0 |

**Veredicto preliminar:** No está listo para `SearchOrchestrator`. El siguiente módulo crítico a implementar es el cliente real de Wallapop (Playwright) y el `SearchOrchestrator` que orqueste búsqueda → detección → valoración.

---

## 2. Estado Real del Proyecto

### 2.1 Módulos implementados

| Módulo | Estado | Archivo principal |
|--------|--------|---------------------|
| `WallapopClient` (HTTP) | Implementado, pero endpoint obsoleto/bloqueado | `src/infrastructure/marketplaces/wallapop/client.py` |
| `WallapopAdapter` | Placeholder vacío | `src/infrastructure/marketplaces/wallapop/adapter.py` |
| `FuzzyGameDetector` | Implementado y validado con datos reales | `src/infrastructure/detectors/fuzzy_game_detector.py` |
| `RuleBasedComparableFilter` | Implementado | `src/infrastructure/filters/rule_based_comparable_filter.py` |
| `WallapopPriceCollector` | Implementado, depende de cliente real | `src/infrastructure/collectors/wallapop_price_collector.py` |
| `DefaultPriceDatasetBuilder` | Implementado | `src/infrastructure/dataset_builders/default_price_dataset_builder.py` |
| `DefaultPriceStatistics` | Implementado | `src/infrastructure/statistics/default_price_statistics.py` |
| `DefaultOutlierRemoval` | Implementado | `src/infrastructure/outliers/default_outlier_removal.py` |
| `DefaultMarketPriceEstimator` | Implementado | `src/infrastructure/estimators/default_market_price_estimator.py` |
| `DefaultArbitrageOpportunityDetector` | Implementado | `src/infrastructure/detectors/default_arbitrage_opportunity_detector.py` |
| `DefaultOpportunityRanker` | Implementado | `src/infrastructure/rankers/default_opportunity_ranker.py` |
| `DefaultOpportunityScanner` | Implementado | `src/infrastructure/scanners/default_opportunity_scanner.py` |
| `CandidateListing` / `GameValuation` / `LotOpportunity` | Implementados | `src/domain/entities/` |
| `DefaultLotOpportunityAnalyzer` | Implementado | `src/infrastructure/analyzers/default_lot_opportunity_analyzer.py` |
| `DefaultLotOpportunityScanner` | Implementado | `src/infrastructure/scanners/default_lot_opportunity_scanner.py` |
| `SearchOrchestrator` | **NO EXISTE** | — |
| `WallapopPlaywrightClient` | **NO EXISTE** | Solo scripts PoC en `examples/` |

### 2.2 Último módulo funcional

El último módulo funcional completado es **`DefaultLotOpportunityScanner`** junto con **`DefaultLotOpportunityAnalyzer`**, que permiten valorar lotes de juegos a partir de un `CandidateListing` con juegos detectados.

### 2.3 Siguiente módulo no implementado

**`SearchOrchestrator`** (u orquestador de búsqueda). No existe en el repositorio. Es el componente que debería:

1. Recibir criterios de búsqueda (keywords, ubicación, filtros).
2. Ejecutar búsquedas reales en Wallapop.
3. Convertir resultados en `CandidateListing`.
4. Ejecutar `LotOpportunityScanner` o `OpportunityScanner` según el tipo de anuncio.
5. Devolver oportunidades ordenadas.

---

## 3. Última Funcionalidad Implementada

La última funcionalidad implementada es el **pipeline de lotes**:

- `CandidateListing` representa un anuncio candidato (individual o lote).
- `DefaultLotOpportunityScanner` recorre cada juego detectado, ejecuta el pipeline de valoración y llama al analizador.
- `DefaultLotOpportunityAnalyzer` decide `BUY/MAYBE/SKIP` basado en margen, beneficio y confianza agregada.

Está probada con mocks y con dependencias falsas (`FakePriceCollector`, etc.), pero **no conectada a Wallapop real**.

---

## 4. Pipeline Actual

### 4.1 Flujo ideal solicitado vs. flujo real

```text
Wallapop
→ Playwright (no existe como cliente de producción)
→ JSON (capturas manuales en examples/ y responses/)
→ normalización (manual en examples/full_pipeline_example.py)
→ CandidateListing (solo en tests/ejemplos con datos fake)
→ GameDetector (FuzzyGameDetector, funciona con datos reales)
→ clasificación individual/lote (no hay orquestador)
→ LotOpportunityScanner (solo con mocks)
→ resultado
```

### 4.2 Traza archivo por archivo

| Etapa | Clase | Archivo | Entrada | Salida | Instanciado por | Real o mock |
|-------|-------|---------|---------|--------|-----------------|-------------|
| Búsqueda Wallapop | `WallapopClient` | `src/infrastructure/marketplaces/wallapop/client.py` | keywords, lat, lon | JSON raw | Usuario/ejemplo | **Mock/403** |
| Captura Playwright | Script manual | `examples/playwright_capture.py`, `examples/playwright_search.py` | Navegador | JSON guardado | Manual | Real (PoC) |
| Normalización | Manual / ejemplo | `examples/full_pipeline_example.py` | JSON Wallapop | `ComparableListing` | Manual | Real JSON guardado |
| Detección juegos | `FuzzyGameDetector` | `src/infrastructure/detectors/fuzzy_game_detector.py` | `ListingText` | `list[DetectedGame]` | `WallapopPriceCollector` o ejemplo | Real (validado) |
| Clasificación individual/lote | No hay orquestador | — | — | — | — | — |
| Valoración lote | `DefaultLotOpportunityScanner` | `src/infrastructure/scanners/default_lot_opportunity_scanner.py` | `CandidateListing` | `LotScanResult` | Ejemplo/test con mocks | Mock |
| Análisis lote | `DefaultLotOpportunityAnalyzer` | `src/infrastructure/analyzers/default_lot_opportunity_analyzer.py` | `CandidateListing`, `list[GameValuation]` | `LotOpportunity` | Scanner | Real (sin datos reales) |

### 4.3 Conexiones inexistentes

- **No existe cliente Playwright de producción**: los scripts de `examples/` son pruebas de concepto manuales.
- **No existe adaptador de Wallapop a dominio**: `WallapopAdapter` es un placeholder vacío.
- **No existe orquestador de búsqueda**: `SearchOrchestrator` no está implementado.
- **No existe conversión automática de JSON de Wallapop a `CandidateListing`**.

---

## 5. Problemas P0 Críticos

### P0.1 `WallapopClient` usa endpoint obsoleto y recibe 403

- **Severidad:** P0
- **Archivo:** `src/infrastructure/marketplaces/wallapop/client.py:33`
- **Evidencia:** `BASE_URL = "https://api.wallapop.com/api/v3/general/search"`
- **Impacto:** Cualquier llamada real a Wallapop falla con 403. El pipeline completo está bloqueado.
- **Corrección mínima:** Migrar al endpoint real `/api/v3/search/section` (confirmado en `cURL.txt`, `examples/playwright_capture.py`, `examples/playwright_search.py`). Implementar cliente Playwright o capturar headers/cookies necesarios.

### P0.2 No existe `SearchOrchestrator`

- **Severidad:** P0
- **Archivo:** —
- **Evidencia:** Búsqueda por `class SearchOrchestrator` devuelve 0 resultados.
- **Impacto:** No se puede ejecutar un flujo end-to-end real de búsqueda a oportunidad.
- **Corrección mínima:** Implementar `SearchOrchestrator` en `src/application/use_cases/` que coordine: búsqueda → normalización → detección → scanner → ranking.

### P0.3 `WallapopAdapter` es un placeholder vacío

- **Severidad:** P0
- **Archivo:** `src/infrastructure/marketplaces/wallapop/adapter.py`
- **Evidencia:** Clase vacía, sin implementación de `IMarketplaceAdapter`.
- **Impacto:** No hay adaptador de dominio para convertir respuestas de Wallapop en entidades del dominio.
- **Corrección mínima:** Implementar `WallapopAdapter` con método `to_candidate_listing(raw)` y `to_comparable_listing(raw)`.

### P0.4 No se puede ejecutar pipeline real sin JSON guardado

- **Severidad:** P0
- **Archivo:** `examples/full_pipeline_example.py`, `responses/`
- **Evidencia:** El ejemplo de pipeline completo carga `responses/gta_5_ps4.json`.
- **Impacto:** El sistema solo funciona con datos estáticos; no hay flujo real.
- **Corrección mínima:** Conectar `SearchOrchestrator` con cliente Playwright real.

---

## 6. Problemas P1 Importantes

### P1.1 Duplicación de `RankingResult`

- **Severidad:** P1
- **Archivos:** `src/domain/interfaces/opportunity_ranker.py:67` y `src/domain/interfaces/opportunity_scanner.py:96`
- **Evidencia:** Dos clases `RankingResult` con campos y métodos similares pero no idénticos.
- **Impacto:** Inconsistencia en el dominio; el ranker real usa la de `opportunity_ranker.py`, mientras que el scanner usa la de `opportunity_scanner.py`.
- **Corrección mínima:** Unificar en una sola clase en `domain/interfaces/opportunity_ranker.py` y eliminar la duplicada.

### P1.2 `ComparableListing` vs. `Listing` vs. `CandidateListing`

- **Severidad:** P1
- **Archivos:**
  - `src/domain/interfaces/price_collector.py:13` (`ComparableListing`)
  - `src/domain/interfaces/comparable_filter.py:14` (`Listing`)
  - `src/domain/entities/candidate_listing.py:15` (`CandidateListing`)
- **Evidencia:** Tres clases similares con campos superpuestos pero semánticas distintas.
- **Impacto:** Riesgo de conversiones manuales inconsistentes al conectar el pipeline. `CandidateListing` no se usa en ningún scanner real.
- **Corrección mínima:** Definir un `Listing` base en dominio y derivar `ComparableListing` y `CandidateListing` de él, o alinear campos y conversiones.

### P1.3 `DefaultOpportunityScanner` contiene lógica de orquestación en infraestructura

- **Severidad:** P1
- **Archivo:** `src/infrastructure/scanners/default_opportunity_scanner.py`
- **Evidencia:** El scanner coordina 8 pasos del pipeline.
- **Impacto:** Violación de Clean Architecture; la orquestación de casos de uso debería estar en `application/use_cases/`.
- **Corrección mínima:** Mover la orquestación a un caso de uso en `application/use_cases/scan_opportunity.py` y dejar el scanner como implementación de un puerto más ligero.

### P1.4 `DefaultLotOpportunityScanner` también contiene orquestación en infraestructura

- **Severidad:** P1
- **Archivo:** `src/infrastructure/scanners/default_lot_opportunity_scanner.py`
- **Evidencia:** Coordina la valoración de cada juego y llama al analizador.
- **Impacto:** Misma desviación arquitectónica que el punto anterior.
- **Corrección mínima:** Extraer la orquestación a un caso de uso de aplicación.

### P1.5 `opportunity_scanner.py` define estrategias no implementadas con fallback silencioso

- **Severidad:** P1
- **Archivo:** `src/domain/interfaces/opportunity_scanner.py:174-186`
- **Evidencia:** `_sort_by_strategy` hace `logger.warning(...)` y fallback a `OPPORTUNITY_SCORE` para `ABSOLUTE_PROFIT`, `ROI`, etc.
- **Impacto:** El usuario puede pensar que usa una estrategia cuando en realidad se ignora.
- **Corrección mínima:** Lanzar `NotImplementedError` o `UnsupportedRankingStrategyError` para estrategias no implementadas.

### P1.6 `FuzzyGameDetector` depende de catálogo JSON en `data/` que está en `.gitignore`

- **Severidad:** P1
- **Archivo:** `src/infrastructure/detectors/fuzzy_game_detector.py:73`
- **Evidencia:** `catalog_path = Path(__file__).parent.parent.parent.parent / "data" / "game_catalog.json"`
- **Impacto:** El directorio `data/` está ignorado; en un entorno limpio el detector falla con `FileNotFoundError`.
- **Corrección mínima:** Incluir `game_catalog.json` en el repositorio o permitir inyección del catálogo.

---

## 7. Problemas P2 de Mantenimiento

### P2.1 55 errores de lint (ruff), 49 auto-fixables

- **Severidad:** P2
- **Evidencia:** `ruff check src tests examples` reporta F541, F401, UP017, I001, SIM118, SIM102, F841.
- **Impacto:** Higiene del código, pero no bloquea funcionalidad.
- **Corrección mínima:** Ejecutar `ruff check src tests examples --fix`.

### P2.2 `PROJECT_STATUS.md` está desactualizado

- **Severidad:** P2
- **Archivo:** `PROJECT_STATUS.md`
- **Evidencia:** Indica "Phase 3: Domain Layer Implementation" como siguiente paso, pero el dominio ya está implementado.
- **Impacto:** Documentación confusa para nuevos desarrolladores.
- **Corrección mínima:** Actualizar el estado del proyecto y la lista de fases.

### P2.3 `ARCHITECTURE.md` describe entidades que no existen

- **Severidad:** P2
- **Archivo:** `ARCHITECTURE.md`
- **Evidencia:** Menciona `Listing`, `Game`, `DetectedGame`, `GamePrice`, `Opportunity` con propiedades que no coinciden con el código actual.
- **Impacto:** Documentación obsoleta.
- **Corrección mínima:** Sincronizar con las entidades reales (`CandidateListing`, `ComparableListing`, `DetectedGame`, `ArbitrageOpportunity`, `LotOpportunity`).

### P2.4 Archivos JSON de respuestas reales y cURL con identificadores en el repo

- **Severidad:** P2
- **Archivos:** `responses/*.json`, `cURL.txt`, `response.json`
- **Evidencia:** `cURL.txt` contiene `mpid`, `trackinguserid`, `x-deviceid`, `search_id`.
- **Impacto:** Datos potencialmente sensibles/identificables en el repositorio.
- **Corrección mínima:** Mover a `.gitignore` o sanitizar. Eliminar identificadores personales.

### P2.5 Ejemplos desactualizados o con datos fake

- **Severidad:** P2
- **Archivos:** `examples/opportunity_scanner_example.py`, `examples/lot_opportunity_scanner_example.py`
- **Evidencia:** Usan `MockPriceCollector`, `FakePriceCollector`, etc.
- **Impacto:** Los ejemplos no reflejan el estado real del sistema.
- **Corrección mínima:** Actualizar ejemplos para usar componentes reales o documentar claramente que son demostraciones.

### P2.6 `ComparableListing` permite `detected_game=None` pero el scanner lo rechaza

- **Severidad:** P2
- **Archivo:** `src/infrastructure/scanners/default_opportunity_scanner.py:97`
- **Evidencia:** El scanner devuelve `None` si no hay juego detectado.
- **Impacto:** Inconsistencia de tipos en runtime; `ComparableListing` debería garantizar que tiene juego detectado para ser procesado.
- **Corrección mínima:** Hacer `detected_game` obligatorio en `ComparableListing` o crear un tipo separado para listings candidatos.

---

## 8. Código Muerto o Desconectado

### 8.1 `application/use_cases/` vacío

- **Archivo:** `src/application/use_cases/__init__.py`
- **Impacto:** La capa Application no tiene casos de uso. La orquestación vive en infraestructura.
- **Corrección mínima:** Crear `SearchOrchestrator` o `ScanMarketplaceUseCase` en esta capa.

### 8.2 `WallapopAdapter` vacío

- **Archivo:** `src/infrastructure/marketplaces/wallapop/adapter.py`
- **Impacto:** No hay adaptador de dominio para Wallapop.
- **Corrección mínima:** Implementar adaptador.

### 8.3 `RankingResult` en `opportunity_scanner.py`

- **Archivo:** `src/domain/interfaces/opportunity_scanner.py:96`
- **Impacto:** Clase duplicada y no usada por el ranker real.
- **Corrección mínima:** Eliminar o unificar.

### 8.4 Scripts Playwright solo en `examples/`

- **Archivos:** `examples/playwright_capture.py`, `examples/playwright_search.py`
- **Impacto:** No son parte del sistema productivo.
- **Corrección mínima:** Convertir en `WallapopPlaywrightClient` en infraestructura.

---

## 9. Estado de Tests

### 9.1 Clasificación de tests

| Tipo | Cantidad | Ubicación | Notas |
|------|----------|-----------|-------|
| Unitarios | 346 | `tests/unit/` | Todos con mocks |
| Integración | 0 reales | `tests/integration/` | Solo `__init__.py` |
| E2E | 0 reales | `tests/e2e/` | Solo `__init__.py` |
| Con datos reales | 0 | — | Los datos reales solo se usan en `examples/` y `VALIDATION_REPORT.md` |
| Con mocks | 346 | `tests/unit/` | Todos los tests usan mocks |

### 9.2 Tests que reproducen la implementación

- `tests/unit/test_default_opportunity_ranker.py`: Los tests de ranking son robustos y validan comportamiento, no reproducen lógica.
- `tests/unit/test_default_lot_opportunity_analyzer.py`: Validan reglas de negocio con datos concretos.
- `tests/unit/test_wallapop_price_collector.py`: Validan generación de queries y procesamiento de listings, pero no llaman a Wallapop real.
- `tests/unit/test_default_opportunity_scanner.py` y `test_default_lot_opportunity_scanner.py`: Usan mocks para todos los componentes; validan orquestación, no comportamiento de negocio real.

### 9.3 Cobertura por módulo (resumen)

| Módulo | Cobertura | Líneas faltantes |
|--------|-----------|-------------------|
| `src/infrastructure/marketplaces/wallapop/adapter.py` | 0% | 3 |
| `src/infrastructure/marketplaces/wallapop/client.py` | 85% | 13 (manejo de errores, retries) |
| `src/domain/interfaces/opportunity_scanner.py` | 78% | 14 (fallback de estrategias) |
| `src/infrastructure/filters/rule_based_comparable_filter.py` | 92% | 9 |
| `src/infrastructure/collectors/wallapop_price_collector.py` | 89% | 10 (manejo de errores) |
| Resto del dominio/infraestructura | 94-100% | — |

---

## 10. Estado de Documentación

| Documento | Estado | Problemas |
|-----------|--------|-----------|
| `README.md` | Parcialmente desactualizado | Menciona estructura vacía que ya no lo está |
| `PROJECT_STATUS.md` | Desactualizado | Indica fases antiguas como siguientes pasos |
| `ARCHITECTURE.md` | Desactualizado | Describe entidades que no existen |
| `IMPLEMENTATION_SUMMARY.md` | Actual para Price Collector | Solo cubre ese módulo |
| `VALIDATION_REPORT.md` | Actual para FuzzyGameDetector | Solo cubre ese módulo |
| `PRICE_COLLECTOR.md`, `WALLAPOP_CLIENT.md`, etc. | Específicos por módulo | Pueden estar desincronizados |
| `cURL.txt` | Contiene datos sensibles | Identificadores de dispositivo/tracking |

---

## 11. Orden Mínimo Recomendado de Correcciones

1. **P0.1 + P0.3:** Implementar `WallapopPlaywrightClient` real y `WallapopAdapter` para conectar con el endpoint `/api/v3/search/section`.
2. **P0.2:** Implementar `SearchOrchestrator` en `src/application/use_cases/`.
3. **P1.1:** Unificar `RankingResult` duplicado.
4. **P1.2:** Alinear modelos `Listing`/`ComparableListing`/`CandidateListing`.
5. **P1.3 + P1.4:** Mover orquestación de scanners a casos de uso de aplicación.
6. **P1.5:** Reemplazar fallback silencioso por `NotImplementedError`.
7. **P1.6:** Incluir o inyectar `game_catalog.json` correctamente.
8. **P2.1:** Ejecutar `ruff --fix`.
9. **P2.4:** Sanitizar/eliminar `cURL.txt` y JSONs con identificadores.
10. **P2.2 + P2.3:** Actualizar documentación de estado y arquitectura.

---

## 12. Veredicto: ¿Listo o no para SearchOrchestrator?

**NO ESTÁ LISTO.**

El dominio y la infraestructura interna están bien probados con mocks, pero faltan los componentes críticos para ejecutar un pipeline real:

- Cliente Wallapop funcional (Playwright + endpoint correcto).
- Adaptador de Wallapop a entidades de dominio.
- `SearchOrchestrator` que coordine búsqueda → detección → valoración.

Hasta que no se implementen estos tres componentes, el proyecto no puede ejecutar un flujo end-to-end real Wallapop → `LotOpportunity`.

---

**Fin del informe.**
