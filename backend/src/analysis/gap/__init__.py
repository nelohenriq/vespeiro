"""Parliament-Media Gap Analyzer — measures the gap between what's discussed
in parliament and what's covered by Portuguese media outlets.

Strategy:
1. Query parliament debate articles (source_id = "parlamento") and all PT media articles.
2. Extract key topics/terms from both corpora using TF-IDF.
3. Compute topic overlap and gap metrics.
4. Return structured gap data for frontend visualization.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Models ────────────────────────────────────────────────────────────────────


class TopicGap(BaseModel):
    """A topic discussed in parliament with its media coverage level."""

    topic: str
    parliament_mentions: int = 0
    media_mentions: int = 0
    media_outlets: int = 0
    gap_score: float = 0.0  # 0 = full coverage, 1 = total silence
    top_media_outlets: list[str] = []


class ParliamentGapReport(BaseModel):
    """Full parliament-media gap analysis report."""

    generated_at: datetime
    total_parliament_docs: int = 0
    total_media_articles: int = 0
    overall_gap_score: float = 0.0
    topics: list[TopicGap] = []
    most_discussed_only_parliament: list[str] = []
    most_covered_in_media: list[str] = []


# ── Analyzer ──────────────────────────────────────────────────────────────────


class ParliamentGapAnalyzer:
    """Analyzes the gap between parliamentary debate and media coverage."""

    # Portuguese stopwords + noise words
    _STOPWORDS: set[str] = {
        "de", "a", "o", "que", "e", "do", "da", "em", "um", "para",
        "com", "não", "uma", "os", "no", "se", "na", "por", "mais",
        "as", "dos", "como", "mas", "ao", "ele", "das", "à", "seu",
        "sua", "ou", "quando", "muito", "nos", "já", "eu", "também",
        "só", "pelo", "pela", "até", "isso", "ela", "entre", "depois",
        "sem", "mesmo", "aos", "seus", "quem", "nas", "me", "esse",
        "eles", "estão", "você", "tinha", "foram", "essa", "num",
        "nem", "suas", "meu", "às", "minha", "numa", "pelos", "elas",
        "qual", "nós", "lhe", "deles", "essas", "esses", "pelas",
        "este", "dele", "tu", "te", "vocês", "vos", "lhes", "meus",
        "minhas", "teu", "tua", "teus", "tuas", "nosso", "nossa",
        "nossos", "nossas", "dela", "delas", "este", "esta", "estes",
        "estas", "aquele", "aquela", "aqueles", "aquelas", "isto",
        "aquilo", "estou", "está", "estamos", "estão", "estive",
        "esteve", "estivemos", "estiveram", "estava", "estávamos",
        "estavam", "estivera", "estivéramos", "esteja", "estejamos",
        "estejam", "estivesse", "estivéssemos", "estivessem",
        "estiver", "estivermos", "estiverem", "hei", "há", "havemos",
        "hão", "houve", "houvemos", "houveram", "houvera",
        "houvéramos", "haja", "hajamos", "hajam", "houvesse",
        "houvéssemos", "houvessem", "houver", "houvermos", "houverem",
        "houverei", "houverá", "houveremos", "houverão", "houveria",
        "houveríamos", "houveriam", "sou", "somos", "são", "era",
        "éramos", "eram", "fui", "foi", "fomos", "foram", "fora",
        "fôramos", "seja", "sejamos", "sejam", "fosse", "fôssemos",
        "fossem", "for", "formos", "forem", "serei", "será", "seremos",
        "serão", "seria", "seríamos", "seriam", "tenho", "tem", "temos",
        "têm", "tinha", "tínhamos", "tinham", "tive", "teve", "tivemos",
        "tiveram", "tivera", "tivéramos", "tenha", "tenhamos", "tenham",
        "tivesse", "tivéssemos", "tivessem", "tiver", "tivermos",
        "tiverem", "terei", "terá", "teremos", "terão", "teria",
        "teríamos", "teriam",
    }

    # Parliamentary transcript boilerplate — words that appear in every debate
    # but convey no substantive policy content.
    _PARLIAMENTARY_BOILERPLATE: set[str] = {
        # Titles / roles
        "sr", "sra", "srs", "sras", "exmo", "exma", "exmos", "exmas",
        "presidente", "deputado", "deputada", "deputados", "deputadas",
        "secretário", "secretária", "secretários", "ministro", "ministra",
        "primeiro-ministro",
        # Procedural
        "reunião", "plenária", "plenário", "sessão", "redação",
        "série", "número", "sumário", "ordem", "dia", "ponto",
        "palavra", "aplausos", "vozes", "câmara", "mesa", "tribuna",
        "assembleia", "república", "constituição", "regimento",
        "artigo", "n",
        "votação", "voto", "votos", "abstenção", "abstenções",
        "aprovação", "aprovado", "rejeitado", "unanimidade", "maioria",
        # Temporal
        "horas", "minutos", "segundos", "março", "abril", "maio",
        "junho", "julho", "agosto", "setembro", "outubro", "novembro",
        "dezembro", "janeiro", "fevereiro", "quarta-feira", "quinta-feira",
        "sexta-feira", "segunda-feira", "terça-feira", "sábado", "domingo",
        "hoje", "ontem", "amanhã",
        # Legislative / generic
        "legislatura", "legislativa", "legislativo", "parlamento",
        "governo", "estado", "país", "nação", "lei", "decreto",
        "resolução", "diário", "debate", "intervenção", "inscrição",
        "interpelação", "pergunta", "resposta", "esclarecimento",
        "parlamentar", "grupo", "divisão", "forma", "bancada", "oradora",
        "orador", "oradores", "colegas","senhor","senhora","senhores",
        "senhoras","senhoria","excelência","excelências",
        # Generic action words
        "fazer", "dizer", "dar", "ter", "ver", "ir", "poder",
        "dever", "querer", "saber", "falar", "pedir", "deixar",
        "continuar", "começar", "terminar", "acabar", "passar",
        "apresentar", "agradecer", "cumprimentar", "saudar",
        "felicitar", "congratular", "lamentar", "preocupar",
        "entender", "compreender", "perceber", "concordar",
        "discordar", "perguntar", "responder", "explicar",
        "esclarecer", "informar", "comunicar", "anunciar",
        # Filler
        "portanto", "assim", "então", "ainda", "também", "apenas",
        "após", "ante", "perante", "durante", "sobre", "contudo",
        "todavia", "porém", "embora", "porque", "pois", "logo",
        "aliás", "nomeadamente", "designadamente", "concretamente",
        "obviamente", "evidentemente", "naturalmente", "obviamente",
        "toda", "todo", "todos", "todas", "cada", "outro", "outra",
        "outros", "outras", "algum", "alguma", "alguns", "algumas",
        "muito", "muita", "muitos", "muitas", "pouco", "pouca",
        "poucos", "poucas", "grande", "grandes", "pequeno", "pequena",
        "novo", "nova", "novos", "novas", "bom", "boa", "bons", "boas",
        "melhor", "melhores", "pior", "piores", "maior", "maiores",
        "menor", "menores", "primeiro", "primeira", "segundo", "segunda",
        "último", "última", "anterior", "seguinte", "próximo", "próxima",
        # Parliamentary transcript artifacts
        "reabertura", "interrompida", "declarou", "encerrada",
        "presidente declarou", "foi aprovada", "foi aprovado",
        "foi rejeitada", "foi rejeitado", "foi apresentada",
        "foi apresentado", "tomou", "tomaram", "lugar", "eleito",
        "eleita", "eleitos", "eleitas", "candidato", "candidata",
        "candidatos", "candidatas", "partido", "partidos",        # Common debate filler
        "senhorias", "vossa", "vossas", "excelentíssimo",
        "excelentíssima", "faça", "favor", "possa", "poderá",
        "poderão", "poderia", "poderiam", "devem", "devia",
        "deviam", "devido", "acredito", "acredita", "acreditam",
        "gostaria", "gostava",
        # Generic adverb/conjunction fragments that dominate every debate
        "acordo", "sentido", "longo", "preciso", "particular",
        "milhares", "milhões", "milhar", "milhão",
        "agora", "entanto", "relação", "parte",
        "falta", "podemos", "precisamos", "temos",
    }

    def __init__(self, db_session: object | None = None):
        self.db = db_session

    async def analyze(self) -> ParliamentGapReport:
        """Run the full parliament-media gap analysis."""
        parliament_docs = await self._get_parliament_docs()
        media_docs = await self._get_media_docs()

        if not parliament_docs:
            return ParliamentGapReport(
                generated_at=datetime.now(timezone.utc),
                total_parliament_docs=0,
                total_media_articles=len(media_docs),
            )

        # Extract terms from both corpora.
        # Parliament transcripts from the same session are homogeneous —
        # document-frequency filtering would kill everything, so skip it.
        # Media summaries are heterogeneous, so keep DF filtering.
        parliament_terms = self._extract_key_terms(parliament_docs, use_df_filter=False)
        media_terms = self._extract_key_terms(media_docs, use_df_filter=True)

        # Track per-outlet media coverage
        outlet_terms: dict[str, set[str]] = defaultdict(set)
        for doc in media_docs:
            source = doc.get("source_id", "unknown")
            terms = self._extract_terms_from_text(doc.get("content_text", ""))
            outlet_terms[source] |= terms

        # Compute gap per topic
        topics: list[TopicGap] = []
        all_parl_terms = set(parliament_terms.keys())
        all_media_terms = set(media_terms.keys())

        for term, parl_count in sorted(
            parliament_terms.items(), key=lambda x: -x[1]
        )[:30]:
            media_count = media_terms.get(term, 0)
            # Count outlets covering this term
            covering_outlets = [
                src for src, terms in outlet_terms.items()
                if term in terms
            ]

            # Gap score: 0 if well covered, approaches 1 if not covered
            # Uses log scale so even 1 media mention reduces gap from 1 to ~0.3
            if media_count > 0:
                gap_score = max(0.0, 1.0 - (media_count / max(parl_count, 1)))
            else:
                gap_score = 1.0

            topics.append(TopicGap(
                topic=term,
                parliament_mentions=parl_count,
                media_mentions=media_count,
                media_outlets=len(covering_outlets),
                gap_score=round(gap_score, 3),
                top_media_outlets=covering_outlets[:5],
            ))

        # Overall gap score: weighted average
        total_parl_mentions = sum(t.parliament_mentions for t in topics)
        if total_parl_mentions > 0:
            overall_gap = sum(
                t.gap_score * t.parliament_mentions for t in topics
            ) / total_parl_mentions
        else:
            overall_gap = 0.0

        # Most parliament-only topics
        only_parliament = sorted(
            [t for t in topics if t.media_mentions == 0],
            key=lambda t: -t.parliament_mentions,
        )[:10]

        # Most media-covered
        most_covered = sorted(
            [t for t in topics if t.media_mentions > 0],
            key=lambda t: t.media_mentions,
            reverse=True,
        )[:10]

        return ParliamentGapReport(
            generated_at=datetime.now(timezone.utc),
            total_parliament_docs=len(parliament_docs),
            total_media_articles=len(media_docs),
            overall_gap_score=round(overall_gap, 3),
            topics=topics,
            most_discussed_only_parliament=[
                t.topic for t in only_parliament
            ],
            most_covered_in_media=[
                t.topic for t in most_covered
            ],
        )

    def _extract_key_terms(
        self, docs: list[dict], use_df_filter: bool = True
    ) -> dict[str, int]:
        """Extract key terms from a corpus of documents and count frequency.

        When *use_df_filter* is True, terms appearing in >80% of
        documents are excluded as likely boilerplate. This is useful
        for heterogeneous corpora like media summaries.

        When False (for homogeneous corpora like parliament transcripts
        from the same session), the document-frequency filter is skipped
        — all terms pass the word-level substantive check only.
        """
        from collections import Counter

        total_docs = len(docs)
        if total_docs == 0:
            return {}

        doc_freq: Counter[str] = Counter()
        term_freq: Counter[str] = Counter()

        for doc in docs:
            text = doc.get("content_text", "")
            terms = self._extract_terms_from_text(text)
            term_freq.update(terms)
            for term in terms:
                doc_freq[term] += 1

        filtered: dict[str, int] = {}
        for term, freq in term_freq.most_common(200):
            if freq < 2:
                continue

            # Skip single-word terms — they're too generic for topic extraction
            if " " not in term:
                continue

            if use_df_filter:
                df_pct = doc_freq.get(term, 0) / total_docs
                if df_pct > 0.8:  # >80% of docs → boilerplate
                    continue

            filtered[term] = freq
            if len(filtered) >= 100:
                break

        # Deduplicate fragments AFTER filtering to 100 candidates
        # (running it on raw ~20k terms per doc would be O(n²) = ~400M checks)
        deduped_terms = self._deduplicate_fragments(set(filtered.keys()))
        return {
            t: filtered[t]
            for t in sorted(deduped_terms, key=lambda t: filtered[t], reverse=True)[:50]
        }

    def _is_substantive(self, word: str) -> bool:
        """Check if a word carries substantive meaning (not boilerplate/filler)."""
        return (
            len(word) >= 4  # Short words (1-3 chars) are rarely substantive
            and word not in self._PARLIAMENTARY_BOILERPLATE
            and word not in self._STOPWORDS
        )

    def _extract_terms_from_text(self, text: str) -> set[str]:
        """Extract significant 2-3 word terms from Portuguese text.

        Filters out boilerplate by requiring at least one substantive word
        (length >= 4, not a stopword, not parliamentary boilerplate).
        Also detects capitalized proper nouns from the original text
        (post-filtered through the same boilerplate checks).
        """
        if not text:
            return set()

        # Extract proper nouns (capitalized sequences) from original text
        # before lowercasing: "Joaquim Miranda Sarmento" → "joaquim miranda sarmento"
        proper_nouns: set[str] = set()
        # Match sequences of 2+ capitalized words, supporting hyphens
        for match in re.finditer(
            r"\b([A-ZÀ-Ú][a-zà-ú\-]+(?:\s+[A-ZÀ-Ú][a-zà-ú\-]+)+)\b", text
        ):
            phrase = match.group(1).lower()
            # Filter: at least one substantive word in the phrase
            pwords = phrase.split()
            if any(self._is_substantive(w) for w in pwords):
                proper_nouns.add(phrase)

        # Normalize for n-gram extraction
        text = text.lower()
        text = re.sub(r"[^a-zà-ú\s]", " ", text)

        words = text.split()
        terms: set[str] = set()

        # Bigrams: require at least one substantive word
        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i + 1]
            if w1 in self._STOPWORDS and w2 in self._STOPWORDS:
                continue
            if self._is_substantive(w1) or self._is_substantive(w2):
                terms.add(f"{w1} {w2}")

        # Trigrams: require at least one substantive word
        for i in range(len(words) - 2):
            w1, w2, w3 = words[i], words[i + 1], words[i + 2]
            if w1 in self._STOPWORDS and w2 in self._STOPWORDS and w3 in self._STOPWORDS:
                continue
            if self._is_substantive(w1) or self._is_substantive(w2) or self._is_substantive(w3):
                terms.add(f"{w1} {w2} {w3}")

        # Add detected proper nouns (already filtered for substantive content)
        terms |= proper_nouns

        return terms

    @staticmethod
    def _deduplicate_fragments(terms: set[str]) -> set[str]:
        """Remove terms that are substrings of longer terms.

        E.g. {"bloco de esquerda", "de esquerda", "bloco de"}
        → {"bloco de esquerda"} (longest wins).
        """
        sorted_terms = sorted(terms, key=len, reverse=True)
        keep: set[str] = set()
        for term in sorted_terms:
            # Only keep if not already covered by a longer term
            if not any(term in existing for existing in keep):
                keep.add(term)
        return keep

    async def _get_parliament_docs(self) -> list[dict]:
        """Query parliament debate articles from the DB."""
        if self.db is None:
            return []
        try:
            from sqlalchemy import select
            from src.db.models import Article

            result = await self.db.execute(
                select(Article.content_text, Article.title, Article.id)
                .where(Article.source_id == "parlamento_debates")
                .where(Article.content_text.isnot(None))
                .limit(100)
            )
            return [
                {"content_text": row[0], "title": row[1], "id": row[2]}
                for row in result.all()
            ]
        except Exception as exc:
            logger.warning("Failed to query parliament articles: %s", exc)
            return []

    async def _get_media_docs(self) -> list[dict]:
        """Query Portuguese media articles from the DB."""
        if self.db is None:
            return []
        try:
            from sqlalchemy import select
            from src.db.models import Article, Source

            # Fetch media source IDs and all articles in parallel,
            # then filter in Python to avoid SQLite string comparison quirks.
            src_result = await self.db.execute(
                select(Source.id).where(
                    Source.category.in_(["mainstream", "agency", "international"]),
                )
            )
            media_source_ids = {row[0] for row in src_result.all()}

            if not media_source_ids:
                return []

            # Fetch articles with any text content (body or summary)
            # Mainstream RSS scrapers only store summaries, not full text.
            from sqlalchemy import or_
            result = await self.db.execute(
                select(Article.content_text, Article.summary, Article.title, Article.id, Article.source_id)
                .where(or_(
                    Article.content_text.isnot(None),
                    Article.summary.isnot(None),
                ))
                .limit(500)
            )
            return [
                {
                    # Use content_text if available, else fall back to summary
                    "content_text": row[0] or row[1] or "",
                    "title": row[2],
                    "id": row[3],
                    "source_id": row[4],
                }
                for row in result.all()
                if row[4] in media_source_ids  # Python-side filter
            ]
        except Exception as exc:
            logger.warning("Failed to query media articles: %s", exc)
            return []



