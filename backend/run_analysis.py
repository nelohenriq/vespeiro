#!/usr/bin/env python3
"""CLI entrypoint for narrative divergence analysis.

Compares how a Portuguese outlet covers a story against the original source,
producing a multi-dimension DivergenceReport.

Usage:
    # Fixture mode — compare two saved article files (no database needed)
    python run_analysis.py --fixture-original tests/fixtures/lusa_artigo.txt \\
                           --fixture-version tests/fixtures/publico_versao.txt \\
                           --original-title "Governo anuncia 2.3M€ para saúde" \\
                           --version-title "Governo anuncia investimento na saúde"

    # Quick mode — uses default fixtures + titles from the integration test
    python run_analysis.py

    # Save JSON report to file
    python run_analysis.py --fixture-original ... --fixture-version ... --output report.json

    # Ad-hoc source mode — fetch from two source spiders then compare
    python run_analysis.py --source lusa --outlet publico --cluster-id "story-123"
"""

import argparse
import json
import sys
from pathlib import Path

# ── Lazy-loaded pipeline modules ────────────────────────────────────────────


def _load_fixture(path: str) -> str:
    p = Path(path)
    if not p.exists():
        print(f"❌ Fixture not found: {p.resolve()}")
        sys.exit(1)
    return p.read_text(encoding="utf-8")


def _run_analysis(
    original_source_id: str,
    original_title: str,
    original_text: str,
    outlet_source_id: str,
    outlet_title: str,
    outlet_text: str,
    cluster_id: str,
    *,
    original_language: str = "pt",
    outlet_language: str = "pt",
    output_path: str | None = None,
) -> None:
    """Run the full divergence analysis pipeline and print results.

    Args:
        original_source_id: Source ID for the original article.
        original_title: Title of the original article.
        original_text: Body text of the original article.
        outlet_source_id: Source ID for the Portuguese outlet version.
        outlet_title: Title of the outlet version.
        outlet_text: Body text of the outlet version.
        cluster_id: Story cluster identifier.
        original_language: Language code for the original article (default "pt").
        outlet_language: Language code for the outlet article (default "pt").
        output_path: Optional path to write JSON report.
    """
    from src.analysis.divergence.extractor import extract_article
    from src.analysis.divergence.comparator import compare_articles, analyze_sentiment
    from src.analysis.divergence.reporter import report_to_json, report_to_markdown

    print(f"🔍 Extracting facts from original ({original_source_id})…")
    original = extract_article(
        source_id=original_source_id,
        title=original_title,
        content_text=original_text,
        language=original_language,
    )
    print(f"   ✓ {original.word_count} words, {len(original.facts)} facts, "
          f"{len(original.quotations)} quotes")

    print(f"🔍 Extracting facts from outlet ({outlet_source_id})…")
    version = extract_article(
        source_id=outlet_source_id,
        title=outlet_title,
        content_text=outlet_text,
        language=outlet_language,
    )
    print(f"   ✓ {version.word_count} words, {len(version.facts)} facts, "
          f"{len(version.quotations)} quotes")

    # Sentiment analysis (optional — may be slow on first load)
    print("🎭 Analyzing sentiment (lazy-loads pysentimiento)…")
    orig_sentiment = analyze_sentiment(f"{original_title}. {original_text}")
    pt_sentiment = analyze_sentiment(f"{outlet_title}. {outlet_text}")
    if orig_sentiment:
        print(f"   Original: {orig_sentiment.get('sentiment', '?')}")
    if pt_sentiment:
        print(f"   Outlet:   {pt_sentiment.get('sentiment', '?')}")

    # Compare
    print(f"📐 Comparing articles (cluster {cluster_id})…")
    report = compare_articles(
        story_cluster_id=cluster_id,
        original=original,
        portuguese_version=version,
        original_sentiment=orig_sentiment,
        portuguese_sentiment=pt_sentiment,
    )
    print()

    # Output
    md = report_to_markdown(report)
    print(md)
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if output_path:
        js = report_to_json(report)
        Path(output_path).write_text(js, encoding="utf-8")
        print(f"💾 JSON report saved to {output_path}")

    # Quick summary line
    if report.overall_divergence_score is not None:
        pct = report.overall_divergence_score * 100
        print(f"\n📊 Overall divergence: {pct:.0f}%")
    else:
        print("\n📊 Overall divergence: N/A")


def _run_adhoc(
    source_id: str,
    outlet_id: str,
    cluster_id: str,
    output_path: str | None = None,
) -> None:
    """Fetch articles from two sources, then run divergence analysis."""
    import asyncio

    async def _fetch() -> tuple:
        from src.config import load_sources
        from src.scrapers.loader import get_spider

        config = load_sources()
        src_cfg = next((s for s in config.sources if s.id == source_id), None)
        out_cfg = next((s for s in config.sources if s.id == outlet_id), None)

        if not src_cfg:
            print(f"❌ Source '{source_id}' not found in config")
            sys.exit(1)
        if not out_cfg:
            print(f"❌ Outlet '{outlet_id}' not found in config")
            sys.exit(1)

        print(f"🌐 Fetching articles from {src_cfg.name}…")
        src_spider = get_spider(src_cfg)
        src_articles = await src_spider.fetch(src_cfg.id, src_cfg.url)
        print(f"   Got {len(src_articles)} articles")

        print(f"🌐 Fetching articles from {out_cfg.name}…")
        out_spider = get_spider(out_cfg)
        out_articles = await out_spider.fetch(out_cfg.id, out_cfg.url)
        print(f"   Got {len(out_articles)} articles")

        if not src_articles:
            print(f"❌ No articles fetched from {source_id}")
            sys.exit(1)
        if not out_articles:
            print(f"❌ No articles fetched from {outlet_id}")
            sys.exit(1)

        # Use the most recent article from each
        src_article = src_articles[0]
        out_article = out_articles[0]

        return (
            src_cfg.id, src_article.title, src_article.content_text or src_article.title,
            out_cfg.id, out_article.title, out_article.content_text or out_article.title,
        )

    (
        src_id, src_title, src_text,
        out_id, out_title, out_text,
    ) = asyncio.run(_fetch())

    _run_analysis(
        original_source_id=src_id,
        original_title=src_title,
        original_text=src_text,
        outlet_source_id=out_id,
        outlet_title=out_title,
        outlet_text=out_text,
        cluster_id=cluster_id,
        original_language=src_cfg.language,
        outlet_language=out_cfg.language,
        output_path=output_path,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Narrative divergence analysis — compare original vs outlet coverage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Mutually exclusive modes
    mode = parser.add_argument_group("mode (choose one)")
    mode.add_argument(
        "--fixture-original",
        help="Path to a text file containing the original article",
    )
    mode.add_argument(
        "--fixture-version",
        help="Path to a text file containing the Portuguese outlet version",
    )
    mode.add_argument(
        "--source",
        help="Ad-hoc mode: fetch articles from this source ID (e.g. 'lusa')",
    )
    mode.add_argument(
        "--outlet",
        help="Ad-hoc mode: fetch articles from this outlet ID (e.g. 'publico')",
    )

    parser.add_argument(
        "--original-title",
        default="Original article",
        help="Title for the original article (fixture mode)",
    )
    parser.add_argument(
        "--version-title",
        default="Portuguese version",
        help="Title for the Portuguese version (fixture mode)",
    )
    parser.add_argument(
        "--cluster-id",
        default="cli-analysis",
        help="Story cluster identifier",
    )
    parser.add_argument(
        "--output", "-o",
        help="Write JSON report to this file",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # ── Fixture mode ────────────────────────────────────────────────────────
    if args.fixture_original and args.fixture_version:
        original_text = _load_fixture(args.fixture_original)
        version_text = _load_fixture(args.fixture_version)

        # Detect source IDs from fixture filenames (approximate)
        orig_name = Path(args.fixture_original).stem
        ver_name = Path(args.fixture_version).stem
        original_source_id = _infer_source_id(orig_name)
        outlet_source_id = _infer_source_id(ver_name)

        _run_analysis(
            original_source_id=original_source_id,
            original_title=args.original_title,
            original_text=original_text,
            outlet_source_id=outlet_source_id,
            outlet_title=args.version_title,
            outlet_text=version_text,
            cluster_id=args.cluster_id,
            output_path=args.output,
        )

    # ── Ad-hoc source mode ──────────────────────────────────────────────────
    elif args.source and args.outlet:
        _run_adhoc(
            source_id=args.source,
            outlet_id=args.outlet,
            cluster_id=args.cluster_id,
            output_path=args.output,
        )

    # ── Quick demo mode (default) ──────────────────────────────────────────
    elif not any([args.fixture_original, args.fixture_version, args.source, args.outlet]):
        fixtures_dir = Path(__file__).parent / "tests" / "fixtures"
        default_original = fixtures_dir / "lusa_artigo.txt"
        default_version = fixtures_dir / "publico_versao.txt"

        if not default_original.exists() or not default_version.exists():
            print("❌ Default fixtures not found. Run with explicit paths:\n")
            parser.print_help()
            sys.exit(1)

        print("⚡ Quick demo mode — using default fixtures\n")
        _run_analysis(
            original_source_id="lusa",
            original_title="Governo anuncia 2.3M€ para a saúde",
            original_text=default_original.read_text(encoding="utf-8"),
            outlet_source_id="publico",
            outlet_title="Governo anuncia investimento na saúde",
            outlet_text=default_version.read_text(encoding="utf-8"),
            cluster_id="demo-cluster",
            output_path=args.output,
        )

    else:
        print("❌ Incomplete arguments. Use --fixture-original + --fixture-version, "
              "or --source + --outlet.")
        print()
        parser.print_help()
        sys.exit(1)


def _infer_source_id(stem: str) -> str:
    """Guess the source ID from a fixture filename stem."""
    known = {
        "lusa_artigo": "lusa",
        "publico_versao": "publico",
        "reuters_article": "reuters",
        "rtp_versao": "rtp_noticias",
    }
    for key, sid in known.items():
        if key in stem:
            return sid
    # Fallback: use the part before '_' or '-'
    return stem.split("_")[0].split("-")[0]


if __name__ == "__main__":
    main()
