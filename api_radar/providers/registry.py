from .base import BaseProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, type[BaseProvider]] = {}

    def register(self, provider_cls: type[BaseProvider]) -> type[BaseProvider]:
        provider_id = provider_cls.metadata.provider_id
        if provider_id in self._providers:
            raise ValueError(f"Provider already registered: {provider_id}")
        self._providers[provider_id] = provider_cls
        return provider_cls

    def get(self, provider_id: str) -> type[BaseProvider]:
        return self._providers[provider_id]

    def all(self) -> list[type[BaseProvider]]:
        return list(self._providers.values())


registry = ProviderRegistry()
