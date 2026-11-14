"""Implements retrieval's ``Prices`` with the bundled ``genai-prices`` data (``[ai]`` extra).

Only the copy of the price list installed with the package is read: ``genai_prices.update_prices``
is never started, so nothing is fetched over the network. The package is imported at the first
lookup, never when nothing is configured.
"""

import importlib
from dataclasses import dataclass

from exactdocs.retrieval.constants import (
    FALLBACK_PRICE_PROVIDER,
    GATEWAY_PRICE_KINDS,
    PRICE_PROVIDERS,
    TOKENS_PER_MILLION,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class GenaiPrices:
    """Implements ``ports.driven.Prices`` from ``genai_prices.calc_price``."""

    def input_usd_per_million(self, profile_kind: str, model: str) -> float | None:
        """Price a million input tokens of the model.

        Args:
            profile_kind: The profile's kind.
            model: The model name.

        Returns:
            US dollars, or ``None`` when no list knows the model (or ``genai-prices`` is missing).
        """
        return self._price(profile_kind, model, output=False)

    def output_usd_per_million(self, profile_kind: str, model: str) -> float | None:
        """Price a million output tokens of the model.

        Args:
            profile_kind: The profile's kind.
            model: The model name.

        Returns:
            US dollars, or ``None`` when no list knows the model (or ``genai-prices`` is missing).
        """
        return self._price(profile_kind, model, output=True)

    def _price(self, profile_kind: str, model: str, *, output: bool) -> float | None:
        """Look the model up in the bundled lists.

        Tries the profile kind's provider, then the vendor of a ``vendor/model`` name, then, for a
        gateway kind only, OpenAI's list (a gateway's model is most often one of OpenAI's). A
        model the instance runs itself (``ollama``, ``vllm``, ``local``) is never priced from
        another provider's list: it stays unpriced.

        Args:
            profile_kind: The profile's kind.
            model: The model name.
            output: Price output tokens instead of input tokens.

        Returns:
            US dollars per million tokens, or ``None``.
        """
        try:
            prices = importlib.import_module("genai_prices")
        except ImportError:
            return None
        candidates: list[tuple[str, str]] = []
        if (provider := PRICE_PROVIDERS.get(profile_kind)) is not None:
            candidates.append((provider, model))
        vendor, slash, name = model.partition("/")
        if slash:
            candidates.append((vendor, name))
        if profile_kind in GATEWAY_PRICE_KINDS:
            candidates.append((FALLBACK_PRICE_PROVIDER, name if slash else model))
        if output:
            usage = prices.Usage(output_tokens=TOKENS_PER_MILLION)
        else:
            usage = prices.Usage(input_tokens=TOKENS_PER_MILLION)
        for provider_id, model_ref in candidates:
            try:
                price = prices.calc_price(usage, model_ref=model_ref, provider_id=provider_id)
            except LookupError:
                continue
            return float(price.output_price if output else price.input_price)
        return None
