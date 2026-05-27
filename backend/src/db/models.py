"""SQLAlchemy ORM models for Vespeiro."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Source(Base):
    """A news source / media outlet we monitor."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # e.g. "lusa", "publico"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    articles = relationship("Article", back_populates="source", lazy="dynamic")


class Article(Base):
    """A single article collected from a source."""

    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("sources.id"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    language: Mapped[str | None] = mapped_column(String(5), nullable=True)

    source = relationship("Source", back_populates="articles")
