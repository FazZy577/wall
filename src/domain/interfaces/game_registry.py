"""Local identity repository; providers may attach metadata in later blocks."""

from abc import abstractmethod

from domain.entities.game_record import GameRecord, ReleaseIdentity
from domain.interfaces.game_catalog import IGameCatalog


class IGameRegistry(IGameCatalog):
    @abstractmethod
    def get_game(self, game_id: str) -> GameRecord | None:
        pass

    @abstractmethod
    def save_game(self, game: GameRecord) -> None:
        pass

    @abstractmethod
    def save_release(self, release: ReleaseIdentity, aliases: tuple[str, ...] = ()) -> None:
        pass
