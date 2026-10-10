"""IGDB v4 adapter with Twitch application authentication and bounded requests."""

import asyncio
import json
import time
from typing import Any

import httpx

from application.interfaces.game_metadata import (
    GameMetadata,
    IGameMetadataProvider,
    MetadataUnavailable,
)
from domain.entities.detected_game import Platform

# Exact provider platform names: unknown future platforms remain unsupported.
_PLATFORMS = {p.value.casefold(): p for p in Platform if p is not Platform.UNKNOWN}
_PLATFORMS.update({
    "playstation 2": Platform.PS2, "playstation 3": Platform.PS3,
    "playstation 4": Platform.PS4, "playstation 5": Platform.PS5,
    "xbox series x|s": Platform.XBOX_SERIES, "nintendo gamecube": Platform.GAMECUBE,
    "playstation portable": Platform.PSP, "playstation vita": Platform.PS_VITA,
    "wii": Platform.WII, "wii u": Platform.WII_U,
})


class IgdbMetadataProvider(IGameMetadataProvider):
    def __init__(self, client_id: str, client_secret: str,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport
        self._token = ""
        self._expires_at = 0.0
        self._next_request = 0.0
        self._lock = asyncio.Lock()

    async def search(self, name: str) -> tuple[GameMetadata, ...]:
        if not self._client_id or not self._client_secret:
            raise MetadataUnavailable("IGDB credentials are not configured")
        if not name.strip() or len(name) > 200:
            raise ValueError("Metadata query must contain 1 to 200 characters")
        async with self._lock:
            try:
                async with httpx.AsyncClient(timeout=15.0, transport=self._transport) as client:
                    if time.monotonic() >= self._expires_at:
                        auth = await client.post("https://id.twitch.tv/oauth2/token", data={
                            "client_id": self._client_id, "client_secret": self._client_secret,
                            "grant_type": "client_credentials",
                        })
                        auth.raise_for_status()
                        payload = auth.json()
                        token, expires = payload["access_token"], payload["expires_in"]
                        if not isinstance(token, str) or not token or type(expires) is not int or expires <= 0:
                            raise ValueError("Invalid token payload")
                        self._token = token
                        self._expires_at = time.monotonic() + max(0, expires - 60)
                    await asyncio.sleep(max(0, self._next_request - time.monotonic()))
                    self._next_request = time.monotonic() + 0.3
                    response = await client.post("https://api.igdb.com/v4/games", headers={
                        "Client-ID": self._client_id, "Authorization": f"Bearer {self._token}",
                        "Accept": "application/json",
                    }, content=(f"search {json.dumps(name)}; "
                                "fields id,name,alternative_names.name,platforms.name,"
                                "game_type.type,version_parent,version_title,parent_game,url; limit 50;"))
                    if response.status_code == 401:
                        self._expires_at = 0
                    response.raise_for_status()
                    rows = response.json()
                    if not isinstance(rows, list) or len(rows) >= 50:
                        raise ValueError("Invalid or truncated metadata response")
                    return tuple(self._parse(row) for row in rows)
            except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
                # No upstream response body, token, URL parameters or exception text escapes.
                raise MetadataUnavailable("IGDB request failed or returned incomplete metadata") from None

    @staticmethod
    def _parse(row: Any) -> GameMetadata:
        if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0:
            raise ValueError("Invalid game ID")
        platforms = tuple(dict.fromkeys(
            _PLATFORMS[p["name"].casefold()] for p in row.get("platforms", [])
            if p["name"].casefold() in _PLATFORMS
        ))
        return GameMetadata(
            "igdb", str(row["id"]), row["name"], platforms,
            tuple(alias["name"] for alias in row.get("alternative_names", [])),
            row.get("game_type", {}).get("type", "unknown").casefold(),
            bool(row.get("version_parent") or row.get("version_title") or row.get("parent_game")),
            row.get("url", ""),
        )
