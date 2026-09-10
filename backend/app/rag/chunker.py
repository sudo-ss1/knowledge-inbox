from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str
    token_count: int
