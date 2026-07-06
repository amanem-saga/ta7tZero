"""Database models for Optimus company data (SQLAlchemy ORM)."""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Identity ---
    name = Column(String(500), nullable=False, index=True)
    slug = Column(String(500), nullable=False, unique=True)  # URL slug, e.g. "electro-naji"
    status = Column(String(50), nullable=True)               # "En activite", etc.

    # --- Legal info ---
    ice = Column(String(50), nullable=True, unique=True)     # Identifiant Commun
    registre_commerce = Column(String(200), nullable=True)   # RC number
    identifiant_fiscal = Column(String(100), nullable=True)
    date_creation = Column(Date, nullable=True)
    effectif = Column(String(200), nullable=True)            # employee range
    chiffre_affaires = Column(String(200), nullable=True)    # revenue range

    # --- Classification ---
    sector = Column(String(200), nullable=True, index=True)  # e.g. "Commerce & Negoce"
    category = Column(String(200), nullable=True, index=True)
    sub_category = Column(String(200), nullable=True)

    # --- Description ---
    description = Column(Text, nullable=True)

    # --- Contact ---
    address = Column(Text, nullable=True)
    city = Column(String(200), nullable=True, index=True)
    phone1 = Column(String(50), nullable=True)
    phone2 = Column(String(50), nullable=True)
    phone3 = Column(String(50), nullable=True)
    fax = Column(String(50), nullable=True)

    # --- Location ---
    latitude = Column(Float, nullable=True, index=True)
    longitude = Column(Float, nullable=True, index=True)
    osm_url = Column(Text, nullable=True)

    # --- Metadata ---
    source_url = Column(String(500), nullable=True, unique=True)
    scraped_at = Column(DateTime, default=datetime.utcnow)
    page_number = Column(Integer, nullable=True)  # which listing page it came from

    # --- Relationships ---
    products = relationship("Product", back_populates="company", cascade="all, delete-orphan")
    brands = relationship("Brand", back_populates="company", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_companies_city_sector", "city", "sector"),
        Index("ix_companies_coords", "latitude", "longitude"),
    )

    def __repr__(self):
        return f"<Company(name={self.name!r}, ice={self.ice!r})>"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    category_label = Column(String(200), nullable=True)  # e.g. "Climatisation, conditionnement d'air"
    label = Column(String(500), nullable=True)           # e.g. "Installateurs, maintenance (climatisation)"

    company = relationship("Company", back_populates="products")

    __table_args__ = (
        UniqueConstraint("company_id", "category_label", "label", name="uq_product"),
    )


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)

    company = relationship("Company", back_populates="brands")

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_brand"),
    )


class ScrapeLog(Base):
    """Track scraping progress for resumability."""
    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    page_number = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)  # "started", "completed", "failed"
    companies_found = Column(Integer, default=0)
    companies_scraped = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)