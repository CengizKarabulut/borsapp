from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol

from market_intelligence.features.specs import FeatureSliceKey, FeatureSpec
from market_intelligence.market_data.bars import CanonicalFrame


class FeatureProvider(Protocol):
    spec: FeatureSpec

    def compute(self, frame: CanonicalFrame) -> Any | None: ...


class DependentFeatureProvider(Protocol):
    spec: FeatureSpec
    dependencies: Sequence[FeatureSpec]

    def compute_with_dependencies(
        self,
        frame: CanonicalFrame,
        values: dict[str, Any],
    ) -> Any | None: ...


class FeatureRegistry:
    def __init__(self) -> None:
        self._providers: dict[tuple[str, str, str], FeatureProvider] = {}

    @staticmethod
    def _key(spec: FeatureSpec) -> tuple[str, str, str]:
        return spec.feature_id, spec.implementation, spec.version

    def register(self, provider: FeatureProvider) -> None:
        key = self._key(provider.spec)
        if key in self._providers:
            raise ValueError(f"Feature provider zaten kayıtlı: {key}")
        self._providers[key] = provider

    def resolve(self, spec: FeatureSpec) -> FeatureProvider:
        key = self._key(spec)
        try:
            provider = self._providers[key]
        except KeyError as exc:
            raise KeyError(f"Feature provider bulunamadı: {key}") from exc
        if provider.spec.identity_hash != spec.identity_hash:
            raise ValueError(
                f"Feature parametre/warmup uyuşmazlığı: {spec.feature_id}"
            )
        return provider


_MISSING = object()


class InMemoryFeatureCache:
    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._lock = RLock()

    def get(self, key: FeatureSliceKey) -> tuple[bool, Any]:
        with self._lock:
            value = self._values.get(key.cache_key, _MISSING)
        return (False, None) if value is _MISSING else (True, value)

    def put(self, key: FeatureSliceKey, value: Any) -> None:
        with self._lock:
            self._values[key.cache_key] = value


@dataclass(frozen=True)
class FeatureResolution:
    values: dict[str, Any]
    unavailable: tuple[str, ...]
    cache_hits: int
    computed: int


class FeatureEngine:
    def __init__(
        self,
        registry: FeatureRegistry,
        cache: InMemoryFeatureCache | None = None,
    ) -> None:
        self.registry = registry
        self.cache = cache or InMemoryFeatureCache()

    def resolve(
        self,
        frame: CanonicalFrame,
        specs: Sequence[FeatureSpec],
    ) -> FeatureResolution:
        values: dict[str, Any] = {}
        unavailable: list[str] = []
        cache_hits = 0
        computed = 0
        visiting: set[tuple[str, str, str]] = set()

        def resolve_one(spec: FeatureSpec) -> None:
            nonlocal cache_hits, computed
            if spec.feature_id in values or spec.feature_id in unavailable:
                return
            identity = self.registry._key(spec)
            if identity in visiting:
                raise ValueError(f"Feature bağımlılık döngüsü: {spec.feature_id}")
            visiting.add(identity)
            provider = self.registry.resolve(spec)
            dependencies = tuple(getattr(provider, "dependencies", ()))
            for dependency in dependencies:
                resolve_one(dependency)
            key = FeatureSliceKey(
                instrument_id=frame.instrument_id,
                timeframe=frame.timeframe.value,
                through_bar_time=frame.through_bar_time.isoformat(),
                series_revision=frame.series_revision,
                snapshot_id=frame.snapshot_id,
                price_basis=frame.price_basis.value,
                source=frame.source,
                feature=spec,
            )
            found, value = self.cache.get(key)
            if found:
                cache_hits += 1
            else:
                missing_dependency = any(
                    dependency.feature_id in unavailable for dependency in dependencies
                )
                if missing_dependency:
                    value = None
                elif dependencies:
                    dependency_values = {
                        dependency.feature_id: values[dependency.feature_id]
                        for dependency in dependencies
                    }
                    value = provider.compute_with_dependencies(frame, dependency_values)
                else:
                    value = provider.compute(frame)
                self.cache.put(key, value)
                computed += 1
            if value is None:
                unavailable.append(spec.feature_id)
            else:
                values[spec.feature_id] = value
            visiting.remove(identity)

        for spec in specs:
            resolve_one(spec)
        return FeatureResolution(values, tuple(unavailable), cache_hits, computed)
