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

from datetime import datetime, timezone
from typing import Any

import httpx

# ── Default thresholds (can be overridden per-call) ─────────────────────────
DEFAULT_DIVERGENCE_THRESHOLD = 0.35
DEFAULT_SILENCE_STD_DEV_MULTIPLIER = 2.0


# ═══════════════════════════════════════════════════════════════════════════════
#  TelegramBot
# ═══════════════════════════════════════════════════════════════════════════════

class TelegramBot:
    """Send formatted messages to a Telegram chat via the Bot API.

    All methods return ``True`` on success, ``False`` on failure.  Errors are
    logged to stderr so they don't crash the calling pipeline.
    """

    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._client = http_client  # optional injection for testing

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
        divergence_threshold: float = DEFAULT_DIVERGENCE_THRESHOLD,
    ) -> bool:
        """Send an anomaly alert.

        Args:
            anomaly_type: One of ``"divergence"``, ``"silence"``, ``"system"``.
            details: Key-value pairs describing the anomaly (e.g. outlet name,
                     score, threshold, etc.).
            divergence_threshold: Threshold used (for display only).

        Returns:
            ``True`` if sent successfully.
        """
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

    @staticmethod
    def _build_daily_report(stats: Any) -> list[str]:
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
                icon = "⚠️" if od.avg >= DEFAULT_DIVERGENCE_THRESHOLD else "✓"
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

        # ── Divergence anomalies ────────────────────────────────────────────
        anomalies: list[str] = []
        if div.global_avg is not None:
            for outlet_id, od in sorted(div.per_outlet.items(), key=lambda x: x[1].avg, reverse=True):
                if od.avg >= DEFAULT_DIVERGENCE_THRESHOLD:
                    label = outlet_id.replace("_", " ").title()
                    opct = od.avg * 100
                    anomalies.append(
                        f"⚠️ Divergência {label} acima do limiar "
                        f"({opct:.0f}% > {DEFAULT_DIVERGENCE_THRESHOLD * 100:.0f}%)"
                    )

        if sil.today > 0 and sil.avg_7d > 0:
            threshold = sil.avg_7d + DEFAULT_SILENCE_STD_DEV_MULTIPLIER * (
                max(sil.avg_7d, 1.0)
            )
            if sil.today > threshold:
                anomalies.append(f"⚠️ Silêncio elevado: {sil.today} > {threshold:.1f} (média 7d: {sil.avg_7d:.1f})")

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
        tl = stats.timelines
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

    @staticmethod
    def _build_anomaly_alert(
        anomaly_type: str,
        details: dict[str, Any],
        divergence_threshold: float,
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
