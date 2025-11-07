from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RawItem:
    source_url: str
    payload: dict  # site-specific raw dict


@dataclass
class NormalizedEvent:
    uid: str
    data: dict  # matches Event columns


class Extractor:
    kind = "base"

    def discover(self, source_url: str) -> list[RawItem]:
        raise NotImplementedError

    def normalize(self, items: list[RawItem]) -> list[NormalizedEvent]:
        raise NotImplementedError

