# Wallapop Playwright Client

## Listing IDs

The client captures the official `id` field from the Wallapop search-section
API response. It trims external whitespace on string IDs and converts integer
IDs confirmed by the legacy payload contract. Items with absent, empty,
boolean, float, or unsupported IDs are omitted. The full URL and `web_slug`
are not identity fallbacks, and case or leading zeroes are never normalized.

## Motivo

El cliente HTTP histórico usa `/api/v3/general/search`. Ese endpoint está
obsoleto para este flujo y actualmente responde con HTTP 403. Se conserva en
`client.py` como implementación legacy/experimental, pero no es la integración
productiva.

`WallapopPlaywrightClient` abre la búsqueda pública de Wallapop en Chromium y
captura la respuesta que el propio navegador recibe desde el endpoint real:

```text
/api/v3/search/section
```

No extrae datos del HTML, no inicia sesión y no copia cookies, identificadores
de tracking ni cabeceras de una cuenta personal.

## Funcionamiento

El cliente implementa el puerto asíncrono `IMarketplaceSearch`:

```python
search_listings(keywords, latitude, longitude, max_results)
```

La primera búsqueda abre Playwright, Chromium, un contexto y una página. Las
búsquedas posteriores reutilizan esos mismos recursos. El context manager
asíncrono garantiza el cierre del contexto, browser y Playwright incluso si el
pipeline lanza una excepción.

Chromium se abre visible por defecto porque esa es la condición validada por el
POC y por los tests live. El modo headless puede activarse con `headless=True`,
pero Wallapop puede no emitir la respuesta de búsqueda en ese modo.

Durante cada navegación se registran respuestas de red, pero solo se encolan
las cuyo host es `api.wallapop.com` y cuya ruta es exactamente
`/api/v3/search/section`. La estructura observada es
`data.section.items`; el cursor opaco está en `meta.next_page`.

La paginación no decodifica el cursor ni presupone un parámetro HTTP. Cuando
existe `meta.next_page`, el cliente desplaza la página y deja que la aplicación
de Wallapop solicite la continuación real. `max_pages` limita el número de
respuestas procesadas y `request_delay` introduce una pausa configurable entre
páginas.

Las respuestas se normalizan al formato que espera `WallapopPriceCollector`:
`id`, `title`, `description`, `price`, `currency` y `web_slug`. El cliente solo
obtiene y normaliza anuncios. El collector genera la consulta, detecta el juego,
descarta anuncios no comparables y crea `ComparableListing`.

## Uso

```python
async with WallapopPlaywrightClient(max_pages=2) as client:
    listings = await client.search_listings(
        keywords="gta 5 ps4",
        latitude=40.4168,
        longitude=-3.7038,
        max_results=5,
    )
```

Chromium debe estar instalado una vez:

```powershell
py -m uv run playwright install chromium
```

## Tests

Los tests unitarios usan mocks de Playwright y nunca abren un navegador:

```powershell
py -m uv run pytest tests/unit/test_wallapop_playwright_client.py -v
```

Los tests reales están desactivados por defecto. Para ejecutarlos en
PowerShell:

```powershell
$env:RUN_LIVE_WALLAPOP_TESTS="1"
py -m uv run pytest -m live -v
```

En shells POSIX:

```bash
RUN_LIVE_WALLAPOP_TESTS=1 uv run pytest -m live -v
```

El test de integración pide como máximo cinco anuncios. El E2E ejecuta el
pipeline mínimo hasta `MarketPriceEstimator`, sin lotes, persistencia ni
`OpportunityScanner`.

## Debugging y seguridad

No se guardan respuestas por defecto. Para depuración local puede pasarse
`debug_response_dir`; los nombres generados no contienen la consulta. No debe
usarse esa opción con datos que se vayan a publicar.

`.gitignore` excluye capturas JSON, cURL, HAR, perfiles, cookies y storage state.
Algunos archivos de captura ya estaban versionados antes de esta corrección. Si
el repositorio fue publicado, eliminarlos del historial Git requiere una tarea
de seguridad separada; esta fase no reescribe el historial.

## Limitaciones

- Depende de la estructura pública y del comportamiento de scroll de Wallapop.
- Actualmente la configuración live validada requiere Chromium visible.
- Los cambios del frontend o del endpoint pueden requerir adaptar la captura.
- Las pruebas live dependen de red, disponibilidad de Wallapop y Chromium.
- No se ejecutan en CI ni con `pytest` normal salvo activación explícita.
- No implementa persistencia, login, alertas ni `SearchOrchestrator`.
