-- Migration 082: countries-Tabelle für v2-Architektur erweitern.
--
-- Hintergrund: Plan rosy-dancing-pond.md — wir bauen ein Schema auf numerischen
-- IDs auf (country_id, family_id, instance_id, series_pk). countries hatte bisher
-- nur `code` (text) als PK. Wir ergänzen einen SERIAL country_id, ohne den
-- bestehenden code-PK anzufassen (damit Foreign Keys aus data_points etc. nicht
-- brechen). Die neuen v2-Tabellen referenzieren ausschließlich country_id.

ALTER TABLE countries
  ADD COLUMN IF NOT EXISTS country_id        SERIAL UNIQUE,
  ADD COLUMN IF NOT EXISTS iso_alpha3        TEXT,
  ADD COLUMN IF NOT EXISTS currency_code     TEXT,
  ADD COLUMN IF NOT EXISTS eurostat_geo_code TEXT,
  ADD COLUMN IF NOT EXISTS te_country_path   TEXT;

COMMENT ON COLUMN countries.country_id        IS 'Numerische ID für v2-Schema FKs (te_source_attributions, indicator_instances, te_page_snapshots, te_audit_findings).';
COMMENT ON COLUMN countries.iso_alpha3        IS 'ISO 3166-1 alpha-3 (USA, DEU, GBR, ...). Reserviert für künftige Library/Provider die alpha-3 statt alpha-2 erwarten.';
COMMENT ON COLUMN countries.currency_code     IS 'ISO 4217 Default-Currency für Display (USD, EUR, GBP, ...).';
COMMENT ON COLUMN countries.eurostat_geo_code IS 'Eurostat geo-Code wenn != ISO alpha-2 (z.B. EL für GR, UK für GB).';
COMMENT ON COLUMN countries.te_country_path   IS 'TE-URL-Slug (united-states, czech-republic, united-kingdom, ...). Wird von te_parser.py + indicator_instances.te_url genutzt.';

-- Backfill: ISO Alpha-3, Währung, Eurostat-Code, TE-Path
-- (Alle 31 Länder die wir aktuell tracken plus EA für indicator_families.)
UPDATE countries SET iso_alpha3='USA', currency_code='USD', eurostat_geo_code='US', te_country_path='united-states'    WHERE code='US';
UPDATE countries SET iso_alpha3='GBR', currency_code='GBP', eurostat_geo_code='UK', te_country_path='united-kingdom'   WHERE code='GB';
UPDATE countries SET iso_alpha3='DEU', currency_code='EUR', eurostat_geo_code='DE', te_country_path='germany'          WHERE code='DE';
UPDATE countries SET iso_alpha3='FRA', currency_code='EUR', eurostat_geo_code='FR', te_country_path='france'           WHERE code='FR';
UPDATE countries SET iso_alpha3='ITA', currency_code='EUR', eurostat_geo_code='IT', te_country_path='italy'            WHERE code='IT';
UPDATE countries SET iso_alpha3='ESP', currency_code='EUR', eurostat_geo_code='ES', te_country_path='spain'            WHERE code='ES';
UPDATE countries SET iso_alpha3='NLD', currency_code='EUR', eurostat_geo_code='NL', te_country_path='netherlands'      WHERE code='NL';
UPDATE countries SET iso_alpha3='BEL', currency_code='EUR', eurostat_geo_code='BE', te_country_path='belgium'          WHERE code='BE';
UPDATE countries SET iso_alpha3='AUT', currency_code='EUR', eurostat_geo_code='AT', te_country_path='austria'          WHERE code='AT';
UPDATE countries SET iso_alpha3='PRT', currency_code='EUR', eurostat_geo_code='PT', te_country_path='portugal'         WHERE code='PT';
UPDATE countries SET iso_alpha3='GRC', currency_code='EUR', eurostat_geo_code='EL', te_country_path='greece'           WHERE code='GR';
UPDATE countries SET iso_alpha3='IRL', currency_code='EUR', eurostat_geo_code='IE', te_country_path='ireland'          WHERE code='IE';
UPDATE countries SET iso_alpha3='FIN', currency_code='EUR', eurostat_geo_code='FI', te_country_path='finland'          WHERE code='FI';
UPDATE countries SET iso_alpha3='LUX', currency_code='EUR', eurostat_geo_code='LU', te_country_path='luxembourg'       WHERE code='LU';
UPDATE countries SET iso_alpha3='SVK', currency_code='EUR', eurostat_geo_code='SK', te_country_path='slovakia'         WHERE code='SK';
UPDATE countries SET iso_alpha3='SVN', currency_code='EUR', eurostat_geo_code='SI', te_country_path='slovenia'         WHERE code='SI';
UPDATE countries SET iso_alpha3='EST', currency_code='EUR', eurostat_geo_code='EE', te_country_path='estonia'          WHERE code='EE';
UPDATE countries SET iso_alpha3='LVA', currency_code='EUR', eurostat_geo_code='LV', te_country_path='latvia'           WHERE code='LV';
UPDATE countries SET iso_alpha3='LTU', currency_code='EUR', eurostat_geo_code='LT', te_country_path='lithuania'        WHERE code='LT';
UPDATE countries SET iso_alpha3='CYP', currency_code='EUR', eurostat_geo_code='CY', te_country_path='cyprus'           WHERE code='CY';
UPDATE countries SET iso_alpha3='MLT', currency_code='EUR', eurostat_geo_code='MT', te_country_path='malta'            WHERE code='MT';
UPDATE countries SET iso_alpha3='POL', currency_code='PLN', eurostat_geo_code='PL', te_country_path='poland'           WHERE code='PL';
UPDATE countries SET iso_alpha3='CZE', currency_code='CZK', eurostat_geo_code='CZ', te_country_path='czech-republic'   WHERE code='CZ';
UPDATE countries SET iso_alpha3='HUN', currency_code='HUF', eurostat_geo_code='HU', te_country_path='hungary'          WHERE code='HU';
UPDATE countries SET iso_alpha3='ROU', currency_code='RON', eurostat_geo_code='RO', te_country_path='romania'          WHERE code='RO';
UPDATE countries SET iso_alpha3='BGR', currency_code='BGN', eurostat_geo_code='BG', te_country_path='bulgaria'         WHERE code='BG';
UPDATE countries SET iso_alpha3='HRV', currency_code='EUR', eurostat_geo_code='HR', te_country_path='croatia'          WHERE code='HR';
UPDATE countries SET iso_alpha3='DNK', currency_code='DKK', eurostat_geo_code='DK', te_country_path='denmark'          WHERE code='DK';
UPDATE countries SET iso_alpha3='SWE', currency_code='SEK', eurostat_geo_code='SE', te_country_path='sweden'           WHERE code='SE';
UPDATE countries SET iso_alpha3='CHN', currency_code='CNY', eurostat_geo_code='CN', te_country_path='china'            WHERE code='CN';
-- EA = Euro Area (aggregate für ECB-Reihen; existiert als pseudo-country falls in countries-Table).
UPDATE countries SET iso_alpha3='EUR', currency_code='EUR', eurostat_geo_code='EA', te_country_path='euro-area'        WHERE code='EA';

-- Index für Lookup über numerische ID
CREATE INDEX IF NOT EXISTS idx_countries_country_id ON countries (country_id);
