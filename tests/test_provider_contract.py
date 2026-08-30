import pytest

from api_radar.providers.base import BaseProvider, ProviderMetadata


class IncompleteProvider(BaseProvider):
    metadata = ProviderMetadata("demo", "Demo", "https://example.com")


def test_provider_contract_is_abstract() -> None:
    with pytest.raises(TypeError):
        IncompleteProvider()
