"""Sentiment analysis using pysentimiento (local CPU, $0 API costs).

Provides a reusable SentimentAnalyzer class for the main pipeline,
supporting Portuguese, Spanish, and English out of the box.
All models run locally on CPU — no API calls needed.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Lazy-loaded analyzer cache ──────────────────────────────────────────────

_ANALYZERS: dict[str, Any] = {}


def _get_analyzer(lang: str) -> Any | None:
    """Lazy-load a pysentimiento sentiment analyzer for the given language.

    Caches analyzers globally; returns None if pysentimiento is unavailable.
    """
    if lang not in _ANALYZERS:
        try:
            from pysentimiento import create_analyzer  # type: ignore[import-untyped]

            _ANALYZERS[lang] = create_analyzer(task="sentiment", lang=lang)
            logger.info("Loaded pysentimiento sentiment analyzer for lang=%s", lang)
        except Exception as exc:
            logger.warning(
                "Failed to load pysentimiento for lang=%s: %s. "
                "Sentiment analysis will return None for this language.",
                lang,
                exc,
            )
            _ANALYZERS[lang] = None
    return _ANALYZERS[lang]


# ── Public API ──────────────────────────────────────────────────────────────


class SentimentAnalyzer:
    """Multi-language sentiment analysis using pysentimiento.

    Supported languages: Portuguese (pt), Spanish (es), English (en).
    Falls back gracefully (returns None) if the underlying model cannot be loaded.

    Usage:
        >>> analyzer = SentimentAnalyzer()
        >>> result = analyzer.analyze("Que dia maravilhoso!", lang="pt")
        >>> result["sentiment"]
        'POS'
        >>> result["probas"]
        {'POS': 0.98, 'NEG': 0.01, 'NEU': 0.01}
    """

    SUPPORTED_LANGUAGES = ("pt", "es", "en")

    def analyze(self, text: str, lang: str = "pt") -> dict | None:
        """Analyze sentiment of a single text.

        Args:
            text: The text to analyze.
            lang: Language code — ``"pt"`` (Portuguese), ``"es"`` (Spanish),
                  or ``"en"`` (English).

        Returns:
            A dict with ``"sentiment"`` (str: ``POS``/``NEG``/``NEU``) and
            ``"probas"`` (dict of class probabilities), or ``None`` if the
            model could not be loaded or analysis fails.

        Raises:
            ValueError: If ``lang`` is not a supported language.
        """
        if lang not in self.SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{lang}'. "
                f"Supported: {', '.join(self.SUPPORTED_LANGUAGES)}"
            )

        analyzer = _get_analyzer(lang)
        if analyzer is None:
            return None

        try:
            result = analyzer.predict(text)
            return {
                "sentiment": result.output,
                "probas": result.probas,
            }
        except Exception as exc:
            logger.warning("Sentiment analysis failed for lang=%s: %s", lang, exc)
            return None

    def analyze_batch(self, texts: list[str], lang: str = "pt") -> list[dict | None]:
        """Analyze sentiment for a batch of texts.

        Args:
            texts: List of text strings to analyze.
            lang: Language code (default ``"pt"``).

        Returns:
            List of sentiment dicts (or ``None`` for failed analyses) in the
            same order as the input texts.
        """
        return [self.analyze(t, lang) for t in texts]

    def score(self, result: dict | None) -> float | None:
        """Convert a pysentimiento result dict to a numeric score.

        Returns a value in ``[-1.0, +1.0]`` where:
            - ``+1.0`` = strongly positive
            -  ``0.0`` = neutral
            - ``-1.0`` = strongly negative

        Args:
            result: The dict returned by :meth:`analyze` (or ``None``).

        Returns:
            A float score, or ``None`` if the input was ``None``.
        """
        if result is None:
            return None

        output = result.get("sentiment", "")
        probas = result.get("probas", {})

        if output == "POS":
            return probas.get("POS", 1.0)
        elif output == "NEG":
            return -probas.get("NEG", 1.0)
        elif output == "NEU":
            return 0.0
        return None
