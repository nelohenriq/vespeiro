"""
Vespeiro — Telegram alert bot.

Sends daily "Jornal do Contra" briefings and anomaly alerts to a Telegram chat.

Usage:
    bot = TelegramBot(token="...", chat_id="...")
    await bot.send_daily_report(stats_payload)
    await bot.send_anomaly_alert("divergence", {"outlet": "publico", "score": 0.42})
    await bot.send_test()

Message format uses Telegram HTML parse mode for bold/italic formatting.
No external dependencies beyond httpx (already in the project).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import httpx

from src.alerts.baseline import BaselineThresholds

# ── Preserved backward-compatible constant ───────────────────────────────────
# Re-exported for tests and external callers that may reference it.
DEFAULT_DIVERGENCE_THRESHOLD = 0.35


# ═══════════════════════════════════════════════════════════════════════════════
#  TelegramBot
# ═══════════════════════════════════════════════════════════════════════════════

class TelegramBot:
    """Send formatted messages to a Telegram chat via the Bot API.

    All methods return ``True`` on success, ``False`` on failure.  Errors are
    logged to stderr so they don't crash the calling pipeline.

    Parameters
    ----------
    baseline:
        Optional :class:`BaselineThresholds` instance for data-driven
        anomaly thresholds.  Falls back to hardcoded defaults if not
        provided or no ``baseline.json`` is available.
    """

    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        baseline: BaselineThresholds | None = None,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._client = http_client  # optional injection for testing
        self._baseline = baseline or BaselineThresholds()

    # ── Public API ──────────────────────────────────────────────────────────

    async def send_daily_report(self, stats: Any) -> bool:
        """Send the full Jornal do Contra daily briefing.

        *stats* should be a ``StatsPayload``-like object (Pydantic or plain
        dict/dataclass) with ``.sources``, ``.lusa_dependency``,
        ``.divergence``, ``.silence``, ``.system``, ``.timelines`` sub-objects.

        Returns:
            ``True`` if the message was sent successfully, ``False`` otherwise.
        """
        lines = self._build_daily_report(stats)
        message = "\n".join(lines)
        return await self._send(message)

    async def send_anomaly_alert(
        self,
        anomaly_type: str,
        details: dict[str, Any],
        *,
        divergence_threshold: float | None = None,
    ) -> bool:
        """Send an anomaly alert.

        Args:
            anomaly_type: One of ``"divergence"``, ``"silence"``, ``"system"``.
            details: Key-value pairs describing the anomaly (e.g. outlet name,
                     score, threshold, etc.).
            divergence_threshold: Override threshold (defaults to baseline
                value if available, else hardcoded fallback).

        Returns:
            ``True`` if sent successfully.
        """
        if divergence_threshold is None:
            divergence_threshold = self._get_divergence_threshold()
        lines = self._build_anomaly_alert(anomaly_type, details, divergence_threshold)
        message = "\n".join(lines)
        return await self._send(message)

    async def send_test(self) -> bool:
        """Send a simple test message to verify credentials."""
        message = (
            "🟢 <b>Vespeiro — Teste OK</b>\n\n"
            "O bot Telegram está configurado correctamente.\n"
            f"Chat ID: <code>{self._chat_id}</code>\n"
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}"
        )
        return await self._send(message)

    # ── Message construction ────────────────────────────────────────────────

    def _get_divergence_threshold(self) -> float:
        """Get the divergence anomaly threshold (data-driven or fallback)."""
        return self._baseline.get_divergence_threshold()

    def _get_silence_threshold(self, avg_7d: float) -> float:
        """Get the silence anomaly threshold (data-driven or fallback).

        Delegates to :meth:`BaselineThresholds.get_silence_anomaly_threshold`
        which uses historical stats.json data when available.
        """
        return self._baseline.get_silence_anomaly_threshold(current_avg_7d=avg_7d)

    def _get_lusa_threshold(self, outlet_id: str | None = None) -> float:
        """Get the Lusa dependency anomaly threshold (data-driven or fallback).

        Delegates to :meth:`BaselineThresholds.get_lusa_dependency_threshold`.
        """
        return self._baseline.get_lusa_dependency_threshold(outlet_id=outlet_id)

    def _get_daily_articles_threshold(self) -> dict[str, float | None]:
        """Get the GHA baseline daily articles volume threshold.

        Returns a dict with ``expected_mean``, ``expected_std``, and
        ``threshold`` (all ``None`` when no baseline.json is loaded).

        Delegates to :meth:`BaselineThresholds.get_daily_articles_threshold`.
        """
        return self._baseline.get_daily_articles_threshold()

    def _build_daily_report(self, stats: Any) -> list[str]:
        """Build the HTML-formatted daily briefing lines from a stats object."""
        now = datetime.now(timezone.utc)
        date_label = now.strftime("%d de %B de %Y")
        time_label = now.strftime("%H:%M")

        lines: list[str] = []

        # ── Header ──────────────────────────────────────────────────────────
        lines.append(f"📰 <b>JORNAL DO CONTRA</b>")
        lines.append(f"{date_label}")
        lines.append("")

        # ── Summary ─────────────────────────────────────────────────────────
        s = stats.sources
        lines.append("📊 <b>Resumo</b>")
        lines.append(f"• Fontes: {s.active} activas / {s.total} total")
        lines.append(f"• Artigos: {s.articles_today:,} hoje / {s.articles_total:,} total")
        lines.append("")

        # ── Lusa Dependency ─────────────────────────────────────────────────
        dep = stats.lusa_dependency
        if dep.global_pct is not None:
            lines.append(f"🏢 <b>Dependência da Lusa</b>: {dep.global_pct:.1f}%")
            for outlet_id, od in sorted(dep.per_outlet.items(), key=lambda x: x[1].pct, reverse=True)[:5]:
                label = outlet_id.replace("_", " ").title()
                if od.stories:
                    lines.append(f"• {label}: {od.pct:.1f}% ({od.lusa_derived}/{od.stories})")
                else:
                    lines.append(f"• {label}: {od.pct:.1f}%")
            if len(dep.per_outlet) > 5:
                lines.append(f"• … e mais {len(dep.per_outlet) - 5} fontes")
            lines.append("")

        # ── Narrative Divergence ────────────────────────────────────────────
        div = stats.divergence
        if div.global_avg is not None:
            pct = div.global_avg * 100
            lines.append(f"🔍 <b>Divergência Narrativa</b>: {pct:.0f}%")
            for outlet_id, od in sorted(div.per_outlet.items(), key=lambda x: x[1].avg, reverse=True):
                label = outlet_id.replace("_", " ").title()
                opct = od.avg * 100
                div_threshold = self._get_divergence_threshold()
                icon = "⚠️" if od.avg >= div_threshold else "✓"
                lines.append(f"• {label}: {opct:.0f}% {icon}")
            lines.append("")

        # ── Silence ─────────────────────────────────────────────────────────
        sil = stats.silence
        if sil.today > 0 or sil.avg_7d > 0:
            lines.append(f"🤫 <b>Silêncios</b>: {sil.today} hoje (média 7d: {sil.avg_7d:.1f})")
            for story in sil.top_silenced[:3]:
                gap = story.gap_pct * 100 if story.gap_pct <= 1 else story.gap_pct
                lines.append(f"• <i>{story.title}</i> (gap: {gap:.0f}%)")
            lines.append("")

        # ── Timelines (used by anomaly checks below) ────────────────────────
        tl = stats.timelines

        # ── Divergence anomalies ────────────────────────────────────────────
        anomalies: list[str] = []
        div_threshold = self._get_divergence_threshold()
        if div.global_avg is not None:
            for outlet_id, od in sorted(div.per_outlet.items(), key=lambda x: x[1].avg, reverse=True):
                if od.avg >= div_threshold:
                    label = outlet_id.replace("_", " ").title()
                    opct = od.avg * 100
                    anomalies.append(
                        f"⚠️ Divergência {label} acima do limiar "
                        f"({opct:.0f}% > {div_threshold * 100:.0f}%)"
                    )

        if sil.today > 0 and sil.avg_7d > 0:
            threshold = self._get_silence_threshold(sil.avg_7d)
            if sil.today > threshold:
                anomalies.append(f"⚠️ Silêncio elevado: {sil.today} > {threshold:.1f} (média 7d: {sil.avg_7d:.1f})")

        # ── Lusa dependency anomalies ───────────────────────────────────────
        if dep.global_pct is not None:
            for outlet_id, od in sorted(dep.per_outlet.items(), key=lambda x: x[1].pct, reverse=True):
                lusa_threshold = self._get_lusa_threshold(outlet_id)
                if lusa_threshold < 100.0 and od.pct > lusa_threshold:
                    label = outlet_id.replace("_", " ").title()
                    anomalies.append(
                        f"⚠️ Dependência alta da Lusa — {label}: {od.pct:.0f}% > {lusa_threshold:.0f}%"
                    )

        # ── Scrape volume anomaly (primary: 7-day timeline) ────────────────
        if tl.articles_daily_7d and len(tl.articles_daily_7d) >= 3:
            vals = [float(v) for v in tl.articles_daily_7d]
            n = len(vals)
            mean_7d = sum(vals) / n
            if n >= 2:
                variance = sum((v - mean_7d) ** 2 for v in vals) / (n - 1)
                std_7d = math.sqrt(variance)
            else:
                std_7d = 0.0
            threshold = mean_7d - 2.0 * std_7d
            if s.articles_today < threshold:
                anomalies.append(
                    f"⚠️ Volume de artigos baixo: {s.articles_today:,} < {threshold:.0f} "
                    f"(média 7d: {mean_7d:.0f}, σ={std_7d:.0f})"
                )

        # ── Scrape volume anomaly (secondary: GHA baseline) ─────────────────
        gha = self._get_daily_articles_threshold()
        if gha["threshold"] is not None and s.articles_today < gha["threshold"]:
            anomalies.append(
                f"⚠️ Volume abaixo do baseline GHA: {s.articles_today:,} < {gha['threshold']:.0f} "
                f"(esperado: {gha['expected_mean']:.0f} ± {gha['expected_std']:.0f})"
            )

        if anomalies:
            lines.append("⚡ <b>Alertas</b>")
            for a in anomalies:
                lines.append(f"• {a}")
            lines.append("")

        # ── System Health ──────────────────────────────────────────────────
        sys_m = stats.system
        lines.append("⚙️ <b>Estado do Sistema</b>")
        health_icon = "🟢" if sys_m.sources_failing == 0 else "🟡" if sys_m.sources_failing < 3 else "🔴"
        lines.append(f"{health_icon} {sys_m.sources_healthy}/{s.total} fontes saudáveis")
        if sys_m.sources_failing:
            lines.append(f"   ⚠️ {sys_m.sources_failing} com falhas")
        if sys_m.last_scrape:
            ts = sys_m.last_scrape
            if hasattr(ts, "strftime"):
                ts_str = ts.strftime("%H:%M")
            else:
                ts_str = str(ts)
            lines.append(f"   🕐 Último scrape: {ts_str}")
        if sys_m.last_error:
            lines.append(f"   ❌ Último erro: {sys_m.last_error[:80]}")

        # ── Timeline sparkline ──────────────────────────────────────────────
        if tl.articles_daily_7d:
            max_val = max(tl.articles_daily_7d) or 1
            bar_chars: list[str] = []
            for val in tl.articles_daily_7d:
                ratio = val / max_val
                if ratio >= 0.8:
                    bar_chars.append("█")
                elif ratio >= 0.6:
                    bar_chars.append("▇")
                elif ratio >= 0.4:
                    bar_chars.append("▆")
                elif ratio >= 0.2:
                    bar_chars.append("▅")
                elif ratio > 0:
                    bar_chars.append("▃")
                else:
                    bar_chars.append("▁")
            spark = "".join(bar_chars)
            lines.append(f"   📈 7d: {spark} ({min(tl.articles_daily_7d)}–{max(tl.articles_daily_7d)})")

        # ── Footer ──────────────────────────────────────────────────────────
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"🕐 Gerado às {time_label} · Vespeiro")

        return lines

    def _build_anomaly_alert(
        self,
        anomaly_type: str,
        details: dict[str, Any],
        divergence_threshold: float | None = None,
    ) -> list[str]:
        """Build an anomaly alert message."""
        lines: list[str] = []
        now = datetime.now(timezone.utc)

        ICO = {"divergence": "🔍", "silence": "🤫", "system": "⚙️"}
        TITLE = {"divergence": "Divergência", "silence": "Silêncio", "system": "Sistema"}
        icon = ICO.get(anomaly_type, "⚠️")
        title = TITLE.get(anomaly_type, "Anomalia")

        lines.append(f"{icon} <b>Alerta — {title}</b>")
        lines.append(now.strftime("%d/%m/%Y %H:%M UTC"))
        lines.append("")

        if anomaly_type == "divergence":
            lines.append(f"Fonte: <b>{details.get('outlet', '?')}</b>")
            lines.append(f"Score: {details.get('score', '?'):.0%}")
            lines.append(f"Limiar: {divergence_threshold:.0%}")
            lines.append(f"Diferença: {details.get('score', 0) - divergence_threshold:+.0%}")
            if details.get("avg_omission"):
                lines.append(f"Omissão: {details['avg_omission']:.0%}")
            if details.get("avg_sentiment_shift"):
                lines.append(f"Desvio sentimental: {details['avg_sentiment_shift']:.0%}")

        elif anomaly_type == "silence":
            lines.append(f"Silêncios hoje: <b>{details.get('today', '?')}</b>")
            lines.append(f"Média 7d: {details.get('avg_7d', '?'):.1f}")
            lines.append(f"Limiar: {details.get('threshold', '?'):.1f}")
            if details.get("top_story"):
                lines.append(f"Principal: <i>{details['top_story']}</i>")
                gap_val = details.get('gap_pct', 0)
                gap_display = gap_val * 100 if gap_val <= 1 else gap_val
                lines.append(f"Gap: {gap_display:.0f}%")

        elif anomaly_type == "system":
            lines.append(f"Fontes com falha: <b>{details.get('failing', '?')}</b>")
            lines.append(f"Total de fontes: {details.get('total', '?')}")
            if details.get("last_error"):
                lines.append(f"Erro: {details['last_error'][:80]}")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append(f"🕐 {now.strftime('%H:%M')} · Vespeiro")

        return lines

    # ── HTTP transport ──────────────────────────────────────────────────────

    async def _send(self, text: str) -> bool:
        """POST to the Telegram Bot API with *text* as HTML-formatted message."""
        if not self._token or not self._chat_id:
            print("[telegram] ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
            return False

        url = self.BASE_URL.format(token=self._token)
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        # Use injected client or create a short-lived one
        client = self._client or httpx.AsyncClient()

        try:
            resp = await client.post(url, json=payload, timeout=15.0)
            data = resp.json()
            if resp.is_success and data.get("ok"):
                return True
            print(
                f"[telegram] API error {resp.status_code}: "
                f"{data.get('description', 'unknown')}"
            )
            return False
        except httpx.RequestError as exc:
            print(f"[telegram] Request failed: {exc}")
            return False
        except Exception as exc:
            print(f"[telegram] Unexpected error: {exc}")
            return False
        finally:
            # Only close if we created the client ourselves
            if self._client is None:
                await client.aclose()
