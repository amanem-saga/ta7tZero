"""Database initialization utilities."""

from pathlib import Path
import logging

from sqlalchemy import create_engine, event, text, func
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base, Company, Brand, Product, ScrapeLog
from config import DATABASE_URL, BASE_DIR

logger = logging.getLogger(__name__)


def get_engine():
    """Create SQLAlchemy engine with PostgreSQL-optimised settings."""
    kwargs = {}
    if DATABASE_URL.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        # Enable WAL mode for better concurrent read performance on SQLite
        engine = create_engine(DATABASE_URL, echo=False, **kwargs)

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    else:
        # PostgreSQL-specific pool settings
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
        kwargs["pool_pre_ping"] = True
        engine = create_engine(DATABASE_URL, echo=False, **kwargs)

    return engine


def init_db(engine=None) -> sessionmaker:
    """Create tables and return a session factory."""
    if engine is None:
        engine = get_engine()

    # Ensure the data directory exists for SQLite
    if DATABASE_URL.startswith("sqlite"):
        db_path = Path(DATABASE_URL.split(":///")[-1])
        db_path.parent.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(engine)
    logger.info("Database tables created/verified")
    return sessionmaker(bind=engine)


def get_session(SessionLocal: sessionmaker) -> Session:
    """Get a database session."""
    return SessionLocal()


def company_exists(session: Session, slug: str) -> bool:
    """Check if a company has already been scraped."""
    return session.query(Company.id).filter(Company.slug == slug).first() is not None


def get_unfinished_pages(session: Session, start_page: int = 1) -> set[int]:
    """Return page numbers that need scraping (DB-driven resume).

    A page is "finished" if it has a 'completed' scrape_log with
    companies_found > 0. Everything else is unfinished:
      - Pages never attempted
      - Pages that failed
      - Pages started but not completed (mid-page interruption)
    """
    # Pages that were successfully completed with companies found
    finished = session.query(ScrapeLog.page_number).filter(
        ScrapeLog.status == "completed",
        ScrapeLog.companies_found > 0,
    ).all()
    finished_set = {row[0] for row in finished}

    # We don't know the total number of pages, so we return start_page onward
    # minus the finished ones. The scraper will stop when it finds a page
    # with no "Suivant" button.
    unfinished = set()
    for p in range(start_page, max(finished_set, default=start_page) + 2):
        if p not in finished_set:
            unfinished.add(p)

    return unfinished


def count_companies(session: Session) -> int:
    """Count total companies in the database."""
    return session.query(func.count(Company.id)).scalar() or 0


def get_max_scraped_page(session: Session) -> int:
    """Get the highest page number that has any log entry."""
    result = session.query(func.max(ScrapeLog.page_number)).scalar()
    return result or 0


def save_company(session: Session, data: dict) -> Company:
    """Insert or update a company and its related products/brands."""
    # Parse date
    date_creation = None
    if data.get("date_creation"):
        try:
            from dateutil.parser import parse
            # French dates like "13 janvier 2011" or "2 décembre 2002"
            # dateutil needs a locale hint for French month names
            french_months = {
                "janvier": "January", "février": "February", "fevrier": "February",
                "mars": "March", "avril": "April", "mai": "May", "juin": "June",
                "juillet": "July", "août": "August", "aout": "August",
                "septembre": "September", "octobre": "October",
                "novembre": "November", "décembre": "December", "decembre": "December",
            }
            date_str = data["date_creation"]
            for fr, en in french_months.items():
                date_str = date_str.replace(fr, en)
            date_creation = parse(date_str, dayfirst=True).date()
        except Exception:
            logger.warning(f"Could not parse date: {data.get('date_creation')}")

    # Upsert company
    company = session.query(Company).filter(Company.slug == data["slug"]).first()
    if company is None:
        company = Company(slug=data["slug"])

    company.name = data.get("name")
    company.status = data.get("status")
    company.ice = data.get("ice")
    company.registre_commerce = data.get("rc")
    company.identifiant_fiscal = data.get("fiscal_id")
    company.date_creation = date_creation
    company.effectif = data.get("employees")
    company.chiffre_affaires = data.get("revenue")
    company.sector = data.get("sector")
    company.category = data.get("category")
    company.sub_category = data.get("sub_category")
    company.description = data.get("description")
    company.address = data.get("address")
    company.city = data.get("city")
    company.phone1 = data.get("phone1")
    company.phone2 = data.get("phone2")
    company.phone3 = data.get("phone3")
    company.fax = data.get("fax")
    company.latitude = data.get("latitude")
    company.longitude = data.get("longitude")
    company.osm_url = data.get("osm_url")
    company.source_url = data.get("source_url")
    company.page_number = data.get("page_number")

    session.add(company)
    session.flush()  # get the id

    # Save products
    for prod in data.get("products", []):
        existing = session.query(Product).filter(
            Product.company_id == company.id,
            Product.category_label == prod.get("category_label"),
            Product.label == prod.get("label"),
        ).first()
        if existing is None:
            session.add(Product(
                company_id=company.id,
                category_label=prod.get("category_label"),
                label=prod.get("label"),
            ))

    # Save brands
    for brand_name in data.get("brands", []):
        existing = session.query(Brand).filter(
            Brand.company_id == company.id,
            Brand.name == brand_name,
        ).first()
        if existing is None:
            session.add(Brand(
                company_id=company.id,
                name=brand_name,
            ))

    return company


def log_scrape(session: Session, page: int, status: str,
               found: int = 0, scraped: int = 0, error: str = None):
    """Log a scraping page attempt."""
    from datetime import datetime
    log_entry = ScrapeLog(
        page_number=page,
        status=status,
        companies_found=found,
        companies_scraped=scraped,
        error_message=error,
    )
    if status in ("completed", "failed"):
        log_entry.finished_at = datetime.utcnow()
    session.add(log_entry)
    session.commit()