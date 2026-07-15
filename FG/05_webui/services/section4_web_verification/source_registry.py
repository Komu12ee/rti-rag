from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .adapters import (
    BaseSourceAdapter,
    CentralInformationCommissionAdapter,
    CentralPublicProcurementAdapter,
    ChhattisgarhEprocCurrentAdapter,
    ChhattisgarhEprocLegacyAdapter,
    ChhattisgarhRTIOnlineAdapter,
    ChhattisgarhSICAdapter,
    DepartmentWebsiteAdapter,
    GovernmentEMarketplaceAdapter,
    SafeHttpClient,
    SupremeCourtAdapter,
)
from .config import Section4Config
from .schemas import SearchPlan, SourceHealth


NORMAL_ADAPTER_IDS = (
    "sci_public",
    "cic_disclosures",
    "siccg_disclosures",
    "cg_rti_online",
)

TENDER_ADAPTER_IDS = (
    "cg_eproc_current",
    "cg_eproc_legacy",
    "gem_procurement",
    "cppp_procurement",
)


class SourceRegistry:
    """Server-owned registry of bounded official-source adapters."""

    def __init__(
        self,
        config: Section4Config,
        *,
        adapters: Iterable[BaseSourceAdapter] | None = None,
        http_client: SafeHttpClient | None = None,
        cache: Any | None = None,
    ) -> None:
        self.config = config
        if adapters is None:
            client = http_client or SafeHttpClient(config)
            core_adapters = (
                SupremeCourtAdapter(config, http_client=client, cache=cache),
                CentralInformationCommissionAdapter(config, http_client=client, cache=cache),
                ChhattisgarhSICAdapter(config, http_client=client, cache=cache),
                ChhattisgarhRTIOnlineAdapter(config, http_client=client, cache=cache),
                ChhattisgarhEprocCurrentAdapter(config, http_client=client, cache=cache),
                ChhattisgarhEprocLegacyAdapter(config, http_client=client, cache=cache),
                GovernmentEMarketplaceAdapter(config, http_client=client, cache=cache),
                CentralPublicProcurementAdapter(config, http_client=client, cache=cache),
            )
            department_adapters = tuple(
                DepartmentWebsiteAdapter(
                    config,
                    domain,
                    http_client=client,
                    cache=cache,
                )
                for domain in sorted(config.department_domains)
            )
            adapters = core_adapters + department_adapters

        ordered = tuple(adapters)
        by_id: dict[str, BaseSourceAdapter] = {}
        for adapter in ordered:
            if not isinstance(adapter, BaseSourceAdapter):
                raise TypeError("Registry entries must implement BaseSourceAdapter")
            adapter_id = str(getattr(adapter, "adapter_id", "")).strip()
            if not adapter_id:
                raise ValueError("Registry adapters require a stable adapter_id")
            if adapter_id in by_id:
                raise ValueError(f"Duplicate source adapter ID: {adapter_id}")
            by_id[adapter_id] = adapter

        self._ordered = ordered
        self._by_id = by_id
        self._department_ids = tuple(
            adapter_id
            for adapter_id in by_id
            if adapter_id.startswith("department_")
        )

    def all(self) -> tuple[BaseSourceAdapter, ...]:
        return self._ordered

    def get(self, adapter_id: str) -> BaseSourceAdapter | None:
        return self._by_id.get(str(adapter_id or "").strip())

    @staticmethod
    def _tender_intent(value: Any) -> bool:
        if isinstance(value, SearchPlan):
            return bool(value.tender.tender_intent)
        tender = getattr(value, "tender", None)
        if tender is not None and hasattr(tender, "tender_intent"):
            return bool(tender.tender_intent)
        return bool(getattr(value, "tender_intent", False))

    def select(
        self,
        search_plan: SearchPlan | Any | None = None,
        *,
        tender_intent: bool | None = None,
        enabled_only: bool = False,
    ) -> tuple[BaseSourceAdapter, ...]:
        has_tender_intent = (
            self._tender_intent(search_plan)
            if tender_intent is None
            else bool(tender_intent)
        )
        selected_ids = (
            NORMAL_ADAPTER_IDS
            + self._department_ids
            + (TENDER_ADAPTER_IDS if has_tender_intent else ())
        )
        selected = tuple(
            adapter
            for adapter_id in selected_ids
            if (adapter := self._by_id.get(adapter_id)) is not None
        )
        if enabled_only:
            selected = tuple(
                adapter for adapter in selected if bool(getattr(adapter, "enabled", True))
            )
        return selected

    select_adapters = select

    def health_check(self) -> tuple[SourceHealth, ...]:
        return tuple(adapter.health_check() for adapter in self._ordered)

    def __iter__(self):
        return iter(self._ordered)

    def __len__(self) -> int:
        return len(self._ordered)


def build_source_registry(
    config: Section4Config,
    *,
    http_client: SafeHttpClient | None = None,
    cache: Any | None = None,
) -> SourceRegistry:
    return SourceRegistry(
        config,
        http_client=http_client,
        cache=cache,
    )
