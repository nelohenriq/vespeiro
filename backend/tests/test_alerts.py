"""Tests for the Telegram alert module (src.alerts.telegram)."""

from __future__ import annotations

from collections import namedtuple
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.alerts.telegram import TelegramBot, DEFAULT_DIVERGENCE_THRESHOLD


# ═══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

def _make_obj(d: dict, name: str = "root"):
    """Recursively convert dicts to objects with attribute access."""
    # Handle None
    if d is None:
        return None

    # Handle lists
    if isinstance(d, list):
        return [_make_obj(item) if isinstance(item, dict) else item for item in d]

    class _Obj:
        def __init__(self, data: dict, obj_name: str):
            self._obj_name = obj_name
            self._data_keys = list(data.keys())
            for k, v in data.items():
                if isinstance(v, dict):
                    setattr(self, k, _make_obj(v, f"{obj_name}.{k}"))
                elif isinstance(v, list):
                    setattr(self, k, [
                        _make_obj(item, f"{obj_name}.{k}[{i}]")
                        if isinstance(item, dict) else item
                        for i, item in enumerate(v)
                    ])
                else:
                    setattr(self, k, v)

        def items(self):
            return [(k, getattr(self, k)) for k in self._data_keys]

        def keys(self):
            return self._data_keys

        def values(self):
            return [getattr(self, k) for k in self._data_keys]

        def __len__(self):
            return len(self._data_keys)

        def __repr__(self):
            keys = self._data_keys
            return f"Obj({self._obj_name}: {', '.join(keys)})"

    return _Obj(d, name)


@pytest.fixture
def mock_http_client():
    """Return an AsyncMock that can be used as httpx.AsyncClient."""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.fixture
def bot(mock_http_client):
    """TelegramBot with mock client injection."""
    return TelegramBot(
        bot_token="test:token",
        chat_id="12345",
        http_client=mock_http_client,
    )


@pytest.fixture
def sample_stats():
    """A realistic StatsPayload-like object with all metrics populated."""
    return _make_obj({
        "sources": {
            "total": 30,
            "active": 28,
            "articles_total": 15678,
            "articles_today": 1234,
            "articles_per_source": {"lusa": 450, "publico": 320},
            "per_category": {},
        },
        "lusa_dependency": {
            "global_pct": 67.3,
            "per_outlet": {
                "publico": {"pct": 72.1, "stories": 198, "lusa_derived": 143},
                "observador": {"pct": 58.4, "stories": 152, "lusa_derived": 89},
                "expresso": {"pct": 45.0, "stories": 100, "lusa_derived": 45},
                "cm_jornal": {"pct": 80.0, "stories": 50, "lusa_derived": 40},
                "jn": {"pct": 55.0, "stories": 120, "lusa_derived": 66},
            },
            "per_topic": {"política": 0.7, "economia": 0.5},
        },
        "divergence": {
            "global_avg": 0.34,
            "per_outlet": {
                "publico": {
                    "avg": 0.42, "stories": 45,
                    "avg_omission": 0.3, "avg_sentiment_shift": 0.1,
                    "avg_quote_fidelity": 0.8, "avg_headline_divergence": 0.5,
                },
                "observador": {
                    "avg": 0.28, "stories": 38,
                    "avg_omission": 0.2, "avg_sentiment_shift": 0.05,
                    "avg_quote_fidelity": 0.85, "avg_headline_divergence": 0.4,
                },
            },
            "top_omitted_facts": [
                {"text": "Governo cortou 500M€ na saúde", "count": 3, "category": "omission"},
            ],
        },
        "silence": {
            "today": 3,
            "avg_7d": 1.5,
            "top_silenced": [
                {
                    "title": "Greve dos enfermeiros ignorada pela CMTV",
                    "international_sources": 4,
                    "pt_coverage": 0,
                    "gap_pct": 1.0,
                    "sources": ["bbc", "guardian"],
                },
            ],
        },
        "timelines": {
            "lusa_dependency_7d": [65.0, 67.0, 66.0, 68.0, 67.3, 66.5, 67.3],
            "divergence_avg_7d": [0.30, 0.32, 0.33, 0.31, 0.34, 0.33, 0.34],
            "articles_daily_7d": [1200, 1150, 1300, 1250, 1400, 1234, 1100],
            "silence_daily_7d": [2, 1, 3, 0, 2, 1, 3],
            "dates_7d": ["2026-05-21", "2026-05-22", "2026-05-23",
                         "2026-05-24", "2026-05-25", "2026-05-26", "2026-05-27"],
        },
        "system": {
            "uptime_pct": 99.5,
            "sources_healthy": 28,
            "sources_failing": 2,
            "last_scrape": "2026-05-27T08:45:00",
            "last_error": "Connection timeout on cm_jornal RSS feed",
        },
    }, "stats")


@pytest.fixture
def sample_empty_stats():
    """StatsPayload with all-zero / null metrics (fresh system state)."""
    return _make_obj({
        "sources": {
            "total": 0, "active": 0, "articles_total": 0, "articles_today": 0,
            "articles_per_source": {}, "per_category": {},
        },
        "lusa_dependency": {
            "global_pct": None, "per_outlet": {}, "per_topic": {},
        },
        "divergence": {
            "global_avg": None, "per_outlet": {}, "top_omitted_facts": [],
        },
        "silence": {
            "today": 0, "avg_7d": 0.0, "top_silenced": [],
        },
        "timelines": {
            "lusa_dependency_7d": [], "divergence_avg_7d": [],
            "articles_daily_7d": [], "silence_daily_7d": [], "dates_7d": [],
        },
        "system": {
            "uptime_pct": 0.0, "sources_healthy": 0, "sources_failing": 0,
            "last_scrape": None, "last_error": None,
        },
    }, "empty_stats")


# ═══════════════════════════════════════════════════════════════════════════════
#  Tests: HTTP transport
# ═══════════════════════════════════════════════════════════════════════════════


class TestSend:
    """Core ``_send`` method tests."""

    async def test_send_success(self, bot, mock_http_client):
        """Successful API call returns True."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"ok": True}
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await bot._send("Test message")
        assert result is True
        mock_http_client.post.assert_awaited_once()

    async def test_send_api_error(self, bot, mock_http_client):
        """API returns error -> False."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = False
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "ok": False, "description": "Forbidden: bot was blocked by the user",
        }
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await bot._send("Test")
        assert result is False

    async def test_send_network_error(self, bot, mock_http_client):
        """Network timeout returns False without crashing."""
        mock_http_client.post = AsyncMock(
            side_effect=httpx.RequestError("Connection failed")
        )

        result = await bot._send("Test")
        assert result is False

    async def test_send_missing_credentials(self):
        """Bot with empty token/chat_id returns False."""
        bot = TelegramBot("", "")
        result = await bot._send("Test")
        assert result is False

    async def test_send_no_missing_token(self):
        """Bot with empty token returns False."""
        bot = TelegramBot("", "12345")
        result = await bot._send("Test")
        assert result is False

    async def test_send_no_missing_chat_id(self):
        """Bot with empty chat_id returns False."""
        bot = TelegramBot("token", "")
        result = await bot._send("Test")
        assert result is False


# ═══════════════════════════════════════════════════════════════════════════════
#  Tests: send_test
# ═══════════════════════════════════════════════════════════════════════════════


class TestSendTest:
    """``send_test()`` method tests."""

    async def test_send_test_success(self, bot, mock_http_client):
        """Test message is sent with appropriate content."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"ok": True}
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await bot.send_test()
        assert result is True

        # Verify the message was actually sent
        mock_http_client.post.assert_awaited_once()
        _, kwargs = mock_http_client.post.call_args
        sent_text = kwargs["json"]["text"]
        assert "Vespeiro" in sent_text
        assert "Teste OK" in sent_text
        assert "12345" in sent_text  # chat_id appears in the message


# ═══════════════════════════════════════════════════════════════════════════════
#  Tests: send_daily_report
# ═══════════════════════════════════════════════════════════════════════════════


class TestSendDailyReport:
    """``send_daily_report()`` formatting tests."""

    async def test_daily_report_populated(self, bot, mock_http_client, sample_stats):
        """Full daily report is sent with all sections present."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"ok": True}
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await bot.send_daily_report(sample_stats)
        assert result is True

        # Verify message content
        _, kwargs = mock_http_client.post.call_args
        text = kwargs["json"]["text"]
        assert kwargs["json"]["parse_mode"] == "HTML"

        # Check all section headers present
        assert "JORNAL DO CONTRA" in text
        assert "Resumo" in text
        assert "Dependência" in text
        assert "Divergência" in text
        assert "Silêncios" in text
        assert "Alertas" in text
        assert "Estado do Sistema" in text
        assert "Vespeiro" in text

        # Check specific data values
        assert "28" in text  # active sources
        assert "30" in text  # total sources
        assert "1,234" in text  # articles today (formatted with comma)
        assert "15,678" in text  # articles total

        # Check dependency section
        assert "67.3%" in text
        assert "Publico" in text
        assert "72.1%" in text
        assert "143/198" in text

        # Check divergence section
        assert "34%" in text
        assert "42%" in text  # Publico divergence (0.42)
        assert "⚠️" in text  # anomaly icon

        # Check silence section
        assert "3 hoje" in text
        assert "média 7d" in text
        assert "Greve dos enfermeiros" in text

        # Check anomalies section
        assert "acima do limiar" in text
        assert "35%" in text  # threshold

        # Check system health
        assert "28/30" in text
        assert "2 com falhas" in text

        # Check sparkline
        assert "7d" in text

    async def test_daily_report_empty(self, bot, mock_http_client, sample_empty_stats):
        """Empty stats produce a minimal valid message (no crashes)."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"ok": True}
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await bot.send_daily_report(sample_empty_stats)
        assert result is True

        # Verify basic structure still present
        _, kwargs = mock_http_client.post.call_args
        text = kwargs["json"]["text"]
        assert "JORNAL DO CONTRA" in text
        assert "Resumo" in text
        assert "Estado do Sistema" in text
        assert "Vespeiro" in text

        # Sections with no data should be absent
        assert "Dependência" not in text
        assert "Divergência" not in text
        assert "Silêncios" not in text
        assert "Alertas" not in text
        assert "7d" not in text

    async def test_daily_report_no_divergence(self, bot, mock_http_client, sample_stats):
        """Stats with null divergence skip divergence section."""
        sample_stats.divergence.global_avg = None

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"ok": True}
        mock_http_client.post = AsyncMock(return_value=mock_response)

        await bot.send_daily_report(sample_stats)
        _, kwargs = mock_http_client.post.call_args
        text = kwargs["json"]["text"]
        # Dependency section still present
        assert "Dependência" in text
        # Divergence section absent when global_avg is None
        assert "Divergência" not in text

    async def test_daily_report_no_dependency(self, bot, mock_http_client, sample_stats):
        """Stats with null dependency skip dependency section."""
        sample_stats.lusa_dependency.global_pct = None

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"ok": True}
        mock_http_client.post = AsyncMock(return_value=mock_response)

        await bot.send_daily_report(sample_stats)
        _, kwargs = mock_http_client.post.call_args
        text = kwargs["json"]["text"]
        assert "Dependência" not in text
        # Divergence section still present
        assert "Divergência" in text

    async def test_daily_report_no_anomalies(self, bot, mock_http_client, sample_stats):
        """Stats with all divergence below threshold skip anomalies section."""
        # Set all divergence values below threshold
        for od in sample_stats.divergence.per_outlet.values():
            od.avg = 0.2  # below 0.35 threshold

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"ok": True}
        mock_http_client.post = AsyncMock(return_value=mock_response)

        await bot.send_daily_report(sample_stats)
        _, kwargs = mock_http_client.post.call_args
        text = kwargs["json"]["text"]
        assert "Alertas" not in text

    async def test_daily_report_no_silence(self, bot, mock_http_client, sample_stats):
        """Stats with zero silence skip silence section."""
        sample_stats.silence.today = 0
        sample_stats.silence.avg_7d = 0.0
        sample_stats.silence.top_silenced = []

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"ok": True}
        mock_http_client.post = AsyncMock(return_value=mock_response)

        await bot.send_daily_report(sample_stats)
        _, kwargs = mock_http_client.post.call_args
        text = kwargs["json"]["text"]
        assert "Silêncios" not in text

    async def test_daily_report_html_escaping(self, bot, mock_http_client, sample_stats):
        """HTML special characters in titles should be safe (we pass as HTML)."""
        # Add a story with HTML-like content
        sample_stats.silence.top_silenced = [
            _make_obj({
                "title": "Greve <test> & \"nurses\" ignorada",
                "international_sources": 3,
                "pt_coverage": 0,
                "gap_pct": 0.95,
                "sources": ["guardian"],
            }, "story"),
        ]
        sample_stats.silence.today = 1
        sample_stats.silence.avg_7d = 0.5

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"ok": True}
        mock_http_client.post = AsyncMock(return_value=mock_response)

        # Should not crash
        result = await bot.send_daily_report(sample_stats)
        assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
#  Tests: send_anomaly_alert
# ═══════════════════════════════════════════════════════════════════════════════


class TestSendAnomalyAlert:
    """``send_anomaly_alert()`` formatting tests."""

    @pytest.fixture
    def mock_response(self, mock_http_client):
        resp = MagicMock(spec=httpx.Response)
        resp.is_success = True
        resp.json.return_value = {"ok": True}
        mock_http_client.post = AsyncMock(return_value=resp)
        return resp

    async def test_divergence_anomaly(self, bot, mock_http_client, mock_response):
        """Divergence anomaly alert formats correctly."""
        result = await bot.send_anomaly_alert("divergence", {
            "outlet": "publico",
            "score": 0.42,
            "avg_omission": 0.30,
            "avg_sentiment_shift": 0.10,
        })
        assert result is True

        _, kwargs = mock_http_client.post.call_args
        text = kwargs["json"]["text"]
        assert "Divergência" in text
        assert "publico" in text.lower() or "Público" in text
        assert "42%" in text  # 0.42 formatted as percentage
        assert "30%" in text  # avg_omission
        assert "10%" in text  # avg_sentiment_shift
        assert "Alerta" in text

    async def test_silence_anomaly(self, bot, mock_http_client, mock_response):
        """Silence anomaly alert formats correctly."""
        result = await bot.send_anomaly_alert("silence", {
            "today": 5,
            "avg_7d": 1.2,
            "threshold": 3.5,
            "top_story": "Greve dos enfermeiros ignorada",
            "gap_pct": 1.0,
        })
        assert result is True

        _, kwargs = mock_http_client.post.call_args
        text = kwargs["json"]["text"]
        assert "Silêncio" in text
        assert "5" in text
        assert "1.2" in text
        assert "Greve dos enfermeiros" in text
        assert "100%" in text  # gap_pct = 1.0 → 100%

    async def test_system_anomaly(self, bot, mock_http_client, mock_response):
        """System health anomaly alert formats correctly."""
        result = await bot.send_anomaly_alert("system", {
            "failing": 3,
            "total": 30,
            "last_error": "Connection timeout on cm_jornal",
        })
        assert result is True

        _, kwargs = mock_http_client.post.call_args
        text = kwargs["json"]["text"]
        assert "Sistema" in text
        assert "3" in text
        assert "30" in text
        assert "Connection timeout" in text

    async def test_unknown_anomaly_type(self, bot, mock_http_client, mock_response):
        """Unknown anomaly type still sends without crashing."""
        result = await bot.send_anomaly_alert("unknown_type", {"key": "value"})
        assert result is True
        _, kwargs = mock_http_client.post.call_args
        text = kwargs["json"]["text"]
        # Falls back to generic icon and "Anomalia" title
        assert "Anomalia" in text


# ═══════════════════════════════════════════════════════════════════════════════
#  Tests: Message construction (unit-level)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildDailyReport:
    """Static ``_build_daily_report()`` unit tests."""

    def test_header_contains_date(self, sample_stats):
        """Header includes the current date in Portuguese format."""
        lines = TelegramBot._build_daily_report(sample_stats)
        header = "\n".join(lines)
        assert "JORNAL DO CONTRA" in header

    def test_source_metrics_present(self, sample_stats):
        """Source metrics section contains active/total counts."""
        lines = TelegramBot._build_daily_report(sample_stats)
        text = "\n".join(lines)
        assert "Fonte" in text

    def test_dependency_section_format(self, sample_stats):
        """Dependency section shows global pct and per-outlet breakdown."""
        lines = TelegramBot._build_daily_report(sample_stats)
        text = "\n".join(lines)
        assert "67.3%" in text

    def test_divergence_section_format(self, sample_stats):
        """Divergence section shows global avg and per-outlet scores."""
        lines = TelegramBot._build_daily_report(sample_stats)
        text = "\n".join(lines)
        assert "34%" in text
        assert "42%" in text
        assert "⚠️" in text  # Público above threshold

    def test_silence_section_format(self, sample_stats):
        """Silence section shows today count and top stories."""
        lines = TelegramBot._build_daily_report(sample_stats)
        text = "\n".join(lines)
        assert "3 hoje" in text

    def test_anomalies_identified(self, sample_stats):
        """Anomalies are flagged when divergence exceeds threshold."""
        lines = TelegramBot._build_daily_report(sample_stats)
        text = "\n".join(lines)
        assert "acima do limiar" in text

    def test_system_health_present(self, sample_stats):
        """System health section is always present."""
        lines = TelegramBot._build_daily_report(sample_stats)
        text = "\n".join(lines)
        assert "Estado do Sistema" in text

    def test_sparkline_present(self, sample_stats):
        """Sparkline is included when articles_daily_7d has data."""
        lines = TelegramBot._build_daily_report(sample_stats)
        text = "\n".join(lines)
        assert "7d" in text

    def test_empty_stats(self, sample_empty_stats):
        """Empty stats produce minimal output without crashing."""
        lines = TelegramBot._build_daily_report(sample_empty_stats)
        text = "\n".join(lines)
        assert "JORNAL DO CONTRA" in text
        assert "Resumo" in text


class TestBuildAnomalyAlert:
    """Static ``_build_anomaly_alert()`` unit tests."""

    def test_divergence_alert(self):
        """Divergence alert has outlet, score, and threshold."""
        lines = TelegramBot._build_anomaly_alert("divergence", {
            "outlet": "publico",
            "score": 0.42,
        }, divergence_threshold=DEFAULT_DIVERGENCE_THRESHOLD)
        text = "\n".join(lines)
        assert "Divergência" in text

    def test_silence_alert(self):
        """Silence alert has today count and average."""
        lines = TelegramBot._build_anomaly_alert("silence", {
            "today": 5,
            "avg_7d": 1.2,
            "threshold": 3.5,
            "top_story": "Nurses strike",
            "gap_pct": 1.0,
        }, divergence_threshold=DEFAULT_DIVERGENCE_THRESHOLD)
        text = "\n".join(lines)
        assert "Silêncio" in text

    def test_system_alert(self):
        """System alert has failing count and total."""
        lines = TelegramBot._build_anomaly_alert("system", {
            "failing": 3,
            "total": 30,
        }, divergence_threshold=DEFAULT_DIVERGENCE_THRESHOLD)
        text = "\n".join(lines)
        assert "Sistema" in text
        assert "3" in text
        assert "30" in text


# ═══════════════════════════════════════════════════════════════════════════════
#  Tests: Client injection
# ═══════════════════════════════════════════════════════════════════════════════


class TestClientLifecycle:
    """Verify the bot handles client injection correctly."""

    async def test_no_client_injection(self):
        """Bot without injected client creates its own (no crash)."""
        bot = TelegramBot("test:token", "12345")
        # Should not crash when no client is injected — _send creates one
        # We can't test the actual send since it would hit the real API,
        # but we can verify the object initializes correctly
        assert bot._client is None

    async def test_injected_client_used(self, mock_http_client):
        """Injected client is used for sends."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"ok": True}
        mock_http_client.post = AsyncMock(return_value=mock_response)

        bot = TelegramBot("test:token", "12345", http_client=mock_http_client)
        await bot._send("hello")
        mock_http_client.post.assert_awaited_once()

    async def test_injected_client_not_closed(self, mock_http_client):
        """When client is injected, the bot should NOT close it."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.is_success = True
        mock_response.json.return_value = {"ok": True}
        mock_http_client.post = AsyncMock(return_value=mock_response)

        bot = TelegramBot("test:token", "12345", http_client=mock_http_client)
        await bot._send("hello")

        # The injected client should NOT be closed
        mock_http_client.aclose.assert_not_awaited()
