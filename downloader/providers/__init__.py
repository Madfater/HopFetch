"""Provider registry: maps a user-supplied URL to the provider that can download it.

To add a platform, write a `Provider` subclass in this package and add an instance to
`default_registry`, before `DirectProvider`, which accepts any http(s) URL.
"""

from __future__ import annotations

from .base import FileRef, Provider, ProviderError
from .direct import DirectProvider
from .k2s import K2SProvider


class ProviderRegistry:
    """Ordered list of providers; the first whose `match` accepts a URL wins."""

    def __init__(self, providers: list[Provider]):
        self._providers = list(providers)

    def register(self, provider: Provider, first: bool = True) -> None:
        """Add a provider, by default ahead of the existing ones."""
        if first:
            self._providers.insert(0, provider)
        else:
            self._providers.append(provider)

    def get(self, name: str) -> Provider:
        """Return the provider with `name`, raising KeyError when there is none."""
        for provider in self._providers:
            if provider.name == name:
                return provider
        raise KeyError(name)

    def all(self) -> list[Provider]:
        """Return the providers in match order."""
        return list(self._providers)

    def resolve(self, url: str) -> tuple[Provider, FileRef]:
        """Return the provider and file reference for `url`.

        - A URL on a host owned by a provider must match that provider, so an unsupported
          page such as a folder link is rejected instead of handed to the generic provider.
        - Raises `ProviderError` when no provider accepts the URL.
        """
        url = url.strip()
        for provider in self._providers:
            file_id = provider.match(url)
            if file_id:
                return provider, FileRef(url=url, file_id=file_id)
            if provider.owns_host(url):
                raise ProviderError(f"This {provider.label} URL is not a file link")
        raise ProviderError("Unsupported URL: enter an http(s) link to a file")


def default_registry() -> ProviderRegistry:
    """Return the registry used by the app."""
    return ProviderRegistry([K2SProvider(), DirectProvider()])
