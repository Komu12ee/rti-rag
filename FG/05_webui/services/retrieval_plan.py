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

    @property
    def needs_llm_fallback(self) -> bool:
        return self.route == Route.UNCLEAR or self.confidence < 0.70