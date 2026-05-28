#!/usr/bin/env python3
"""
Vespeiro — Telegram alert bot (Jornal do Contra).

Sends daily briefings and anomaly alerts to a Telegram chat.

Usage:
    # Send test message to verify credentials
    python run_alert.py --test

    # Send daily Jornal do Contra briefing from a stats.json file
    python run_alert.py --daily --stats-path frontend/public/stats.json

    # Send anomaly alert for high divergence on a specific outlet
    python run_alert.py --anomaly divergence --details outlet=publico score=0.42

    # Send anomaly alert for elevated silence
    python run_alert.py --anomaly silence --details today=5 avg_7d=1.2

    # Send anomaly alert for system health
    python run_alert.py --anomaly system --details failing=3 total=30

    # Full pipeline: generate stats then send daily report
    python run_alert.py --daily

Credentials are read from .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) or
can be passed via environment variables directly.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure backend is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

# ── Helpers ──────────────────────────────────────────────────────────────────


def _load_stats_json(path: str) -> dict:
    """Load a stats.json file and return it as a dict."""
    p = Path(path)
    if not p.exists():
        print(f"❌ stats.json not found: {p.resolve()}")
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def _dict_to_obj(d: dict):
    """Convert a nested dict to a simple object with attribute access.

    This lets us pass a plain dict through the TelegramBot formatters
    which expect attribute-style access (e.g. ``stats.sources.articles_today``).
    """
    # Handle None
    if d is None:
        return None

    # Parse datetime strings
    from datetime import datetime

    class _Obj:
        def __init__(self, data: dict):
            self._data_keys = list(data.keys())
            for k, v in data.items():
                if isinstance(v, dict):
                    setattr(self, k, _dict_to_obj(v))
                elif isinstance(v, list):
                    setattr(self, k, [
                        _dict_to_obj(item) if isinstance(item, dict) else item
                        for item in v
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
            return f"Obj({', '.join(keys)})"

    return _Obj(d)


# ═══════════════════════════════════════════════════════════════════════════════
#  Entrypoints
# ═══════════════════════════════════════════════════════════════════════════════


async def cmd_test(token: str, chat_id: str) -> int:
    """Send a test message."""
    from src.alerts.telegram import TelegramBot

    bot = TelegramBot(token, chat_id)
    ok = await bot.send_test()
    if ok:
        print("✅ Test message sent successfully!")
        return 0
    print("❌ Failed to send test message — check token and chat ID")
    return 1


async def cmd_daily(
    token: str,
    chat_id: str,
    stats_path: str | None,
) -> int:
    """Send the daily Jornal do Contra briefing."""
    from src.alerts.telegram import TelegramBot

    # Load stats
    if stats_path:
        raw = _load_stats_json(stats_path)
        stats = _dict_to_obj(raw)
        print(f"📊 Stats loaded from: {stats_path}")
    else:
        # Generate fresh stats
        print("📊 Generating fresh stats from database…")
        from src.config.settings import settings
        from src.stats.generator import StatsGenerator
        from src.db.session import create_engine_and_session, Base
        from sqlalchemy.ext.asyncio import AsyncSession

        db_url = settings.database_url
        engine, session_factory = create_engine_and_session(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session: AsyncSession = session_factory()
        try:
            generator = StatsGenerator(db_session=session)
            stats = await generator.collect()
            print(f"   Sources: {stats.sources.active}/{stats.sources.total} active")
        finally:
            await session.close()
            await engine.dispose()

    bot = TelegramBot(token, chat_id)
    ok = await bot.send_daily_report(stats)
    if ok:
        print("✅ Daily briefing sent successfully!")
        return 0
    print("❌ Failed to send daily briefing")
    return 1


async def cmd_anomaly(
    token: str,
    chat_id: str,
    anomaly_type: str,
    details_raw: list[str],
) -> int:
    """Send an anomaly alert."""
    from src.alerts.telegram import TelegramBot

    # Parse details from key=value pairs
    details: dict = {}
    for pair in details_raw:
        if "=" not in pair:
            print(f"⚠️  Skipping malformed detail: {pair} (expected key=value)")
            continue
        key, _, value = pair.partition("=")
        # Try to parse numeric values
        try:
            if "." in value:
                value = float(value)
            else:
                value = int(value)
        except ValueError:
            pass
        details[key] = value

    bot = TelegramBot(token, chat_id)
    ok = await bot.send_anomaly_alert(anomaly_type, details)
    if ok:
        print(f"✅ Anomaly alert sent for type '{anomaly_type}'!")
        return 0
    print("❌ Failed to send anomaly alert")
    return 1


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Vespeiro Telegram alert bot — Jornal do Contra daily briefings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Credentials
    creds = parser.add_argument_group("credentials (defaults from .env)")
    creds.add_argument("--token", default=None, help="Telegram bot token")
    creds.add_argument("--chat-id", default=None, help="Telegram chat ID")

    # Mode
    mode = parser.add_argument_group("mode (choose one)")
    mode.add_argument(
        "--test",
        action="store_true",
        help="Send a test message to verify credentials",
    )
    mode.add_argument(
        "--daily",
        action="store_true",
        help="Send the daily Jornal do Contra briefing",
    )
    mode.add_argument(
        "--anomaly",
        choices=["divergence", "silence", "system"],
        help="Send an anomaly alert of the given type",
    )

    # Options
    parser.add_argument(
        "--stats-path",
        default=None,
        help="Path to a stats.json file (default: generate fresh from DB)",
    )
    parser.add_argument(
        "--details",
        nargs="*",
        default=[],
        help="Key=value pairs for anomaly alerts (e.g. outlet=publico score=0.42)",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # ── Resolve credentials ────────────────────────────────────────────────
    from src.config.settings import settings

    token = args.token or settings.telegram_bot_token
    chat_id = args.chat_id or settings.telegram_chat_id

    if not token or not chat_id:
        print(
            "❌ TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required.\n"
            "   Set them in .env or pass --token and --chat-id."
        )
        sys.exit(1)

    # ── Route ───────────────────────────────────────────────────────────────
    import asyncio

    if args.test:
        exit_code = asyncio.run(cmd_test(token, chat_id))
    elif args.daily:
        exit_code = asyncio.run(cmd_daily(token, chat_id, args.stats_path))
    elif args.anomaly:
        exit_code = asyncio.run(cmd_anomaly(token, chat_id, args.anomaly, args.details))
    else:
        print("❌ No mode specified. Use --test, --daily, or --anomaly.\n")
        parser.print_help()
        sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
