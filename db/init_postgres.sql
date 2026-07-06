-- ============================================================
-- PostgreSQL DDL for Optimus Meknes Scraper
-- Run this against a real PostgreSQL instance to create the schema.
-- The Python ORM (SQLAlchemy) creates equivalent tables automatically,
-- but this file documents the exact PostgreSQL-native schema.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pg_trgm";   -- for fuzzy name search
CREATE EXTENSION IF NOT EXISTS "postgis";   -- optional: for GIS queries

CREATE TABLE IF NOT EXISTS companies (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(500) NOT NULL,
    slug            VARCHAR(500) NOT NULL UNIQUE,
    status          VARCHAR(50),

    -- Legal
    ice             VARCHAR(50)  UNIQUE,
    registre_commerce VARCHAR(200),
    identifiant_fiscal VARCHAR(100),
    date_creation   DATE,
    effectif        VARCHAR(200),
    chiffre_affaires VARCHAR(200),

    -- Classification
    sector          VARCHAR(200),
    category        VARCHAR(200),
    sub_category    VARCHAR(200),

    -- Description
    description     TEXT,

    -- Contact
    address         TEXT,
    city            VARCHAR(200),
    phone1          VARCHAR(50),
    phone2          VARCHAR(50),
    phone3          VARCHAR(50),
    fax             VARCHAR(50),

    -- Location
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    osm_url         TEXT,

    -- Metadata
    source_url      VARCHAR(500) UNIQUE,
    scraped_at      TIMESTAMPTZ DEFAULT NOW(),
    page_number     INTEGER
);

-- Indexes
CREATE INDEX IF NOT EXISTS ix_companies_name     ON companies (name);
CREATE INDEX IF NOT EXISTS ix_companies_city      ON companies (city);
CREATE INDEX IF NOT EXISTS ix_companies_sector    ON companies (sector);
CREATE INDEX IF NOT EXISTS ix_companies_category  ON companies (category);
CREATE INDEX IF NOT EXISTS ix_companies_ice       ON companies (ice);
CREATE INDEX IF NOT EXISTS ix_companies_coords    ON companies (latitude, longitude);
CREATE INDEX IF NOT EXISTS ix_companies_city_sector ON companies (city, sector);

-- Trigram index for fuzzy search (e.g. search "NAJI" finds "ELECTRO NAJI")
CREATE INDEX IF NOT EXISTS ix_companies_name_trgm ON companies
    USING gin (name gin_trgm_ops);

-- PostGIS geometry column (optional, uncomment if postgis is installed)
-- ALTER TABLE companies ADD COLUMN geom geometry(Point, 4326);
-- CREATE INDEX ix_companies_geom ON companies USING gist (geom);
-- UPDATE companies SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
--     WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

CREATE TABLE IF NOT EXISTS products (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    category_label  VARCHAR(200),
    label           VARCHAR(500),
    CONSTRAINT uq_product UNIQUE (company_id, category_label, label)
);
CREATE INDEX IF NOT EXISTS ix_products_company ON products (company_id);

CREATE TABLE IF NOT EXISTS brands (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name            VARCHAR(200) NOT NULL,
    CONSTRAINT uq_brand UNIQUE (company_id, name)
);
CREATE INDEX IF NOT EXISTS ix_brands_company ON brands (company_id);

CREATE TABLE IF NOT EXISTS scrape_logs (
    id              SERIAL PRIMARY KEY,
    page_number     INTEGER NOT NULL,
    status          VARCHAR(20) NOT NULL,
    companies_found INTEGER DEFAULT 0,
    companies_scraped INTEGER DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_scrape_logs_page ON scrape_logs (page_number);

-- ============================================================
-- Useful queries for the future Vite frontend
-- ============================================================

-- Companies by sector in Meknes
-- SELECT sector, COUNT(*) FROM companies WHERE city = 'Meknes' GROUP BY sector ORDER BY count DESC;

-- Search companies by name (fuzzy)
-- SELECT * FROM companies WHERE name % 'NAJI' ORDER BY similarity(name, 'NAJI') DESC LIMIT 20;

-- Companies near a point (with PostGIS)
-- SELECT name, address, ST_Distance(geom, ST_SetSRID(ST_MakePoint(-5.54, 33.89), 4326)) AS dist_m
-- FROM companies WHERE geom IS NOT NULL ORDER BY geom <-> ST_SetSRID(ST_MakePoint(-5.54, 33.89), 4326) LIMIT 10;

-- Full-text search on description
-- SELECT * FROM companies WHERE to_tsvector('french', description) @@ to_tsquery('french', 'climatisation & électroménager');