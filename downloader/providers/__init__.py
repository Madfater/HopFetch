"""Provider registry: the allowlist that maps a user-supplied URL to the provider that can download it.

To add a platform, write a `Provider` subclass in this package and add an instance to
`default_registry`. A URL that no provider matches is rejected, so the backend never fetches
arbitrary addresses.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from .base import FileRef, Provider, ProviderError, normalize_url
from .dropbox import DropboxProvider
from .k2s import K2SProvider
from .mediafire import MediaFireProvider
from .mega import MegaProvider


class ProviderRegistry:
    """Ordered list of providers; the first whose `match` accepts a URL wins."""

    def __init__(self, providers: list[Provider]):
        self._providers = list(providers)

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

        - Raises `ProviderError("invalid_url")` when the text is not an absolute http(s) URL.
        - Raises `ProviderError("unsupported")` when no provider matches it.
        """
        url = normalize_url(url)
        try:
            parts = urlsplit(url)
            valid = parts.scheme in ("http", "https") and bool(parts.hostname)
        except ValueError:
            valid = False
        if not valid:
            raise ProviderError("invalid_url")
        for provider in self._providers:
            file_id = provider.match(url)
            if file_id:
                return provider, FileRef(url=url, file_id=file_id)
        raise ProviderError("unsupported")


def default_registry() -> ProviderRegistry:
    """Return the registry used by the app."""
    return ProviderRegistry([K2SProvider(), MegaProvider(), MediaFireProvider(), DropboxProvider()])
