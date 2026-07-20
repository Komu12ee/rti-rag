from dataclasses import dataclass
from enum import Enum


class Route(str, Enum):
    POSTGRES = "POSTGRES"
    QDRANT = "QDRANT"
    HYBRID = "HYBRID"
    UNCLEAR = "UNCLEAR"


@dataclass(frozen=True)
class RouterDecision:
    route: Route
    confidence: float
    reason: str
    matched_signals: tuple[str, ...]
