-- Migration 083: te_source_attributions — zentrales Mapping TE-Source-Label → Provider.
--
-- Hintergrund: Sebastian (Feedback): „Das Mapping von unserer Source auf das TE Label,
-- sollte irgendwo zentral passieren". Bisher wurde dasselbe Mapping (z.B. „Statistics
-- Poland" → gus_pl) in jeder per-Country YAML wiederholt und driftete. Wir machen es
-- jetzt zur einzigen Wahrheit: jede indicator_instance referenziert genau eine
-- attribution_id.
--
-- Beispiele:
--   ('Eurostat',           NULL, 'eurostat')   -- global
--   ('European Central Bank', NULL, 'ecb')     -- global
--   ('Federal Reserve',     <US>, 'fred')      -- country-specific
--   ('INSEE',               <FR>, 'insee')
--   ('Statistics Poland',   <PL>, 'gus_pl')

CREATE TABLE IF NOT EXISTS te_source_attributions (
  attribution_id     SERIAL PRIMARY KEY,
  te_label           TEXT NOT NULL,
  te_url             TEXT,
  country_id         INT REFERENCES countries(country_id) ON DELETE SET NULL,
  canonical_provider TEXT NOT NULL,
  notes              TEXT,
  created_at         TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (te_label, country_id)
);

COMMENT ON TABLE  te_source_attributions IS 'Zentrales Mapping: TE-Source-Label (wie auf der TE-Page angezeigt) -> kanonischer Provider in unserer Pipeline. NULL country_id = globaler Provider.';
COMMENT ON COLUMN te_source_attributions.te_label IS 'Exakter Source-Label-Text wie auf der TE-Page, z.B. "INSEE, France" oder "Federal Reserve".';
COMMENT ON COLUMN te_source_attributions.country_id IS 'NULL bei globalem Provider (Eurostat, ECB). country_id bei nationaler Behörde.';
COMMENT ON COLUMN te_source_attributions.canonical_provider IS 'Bevorzugter Provider-Name in unserer pipeline (fred, eurostat, destatis, insee, ...). data_series.fetch_provider darf abweichen, dann muss data_series.source_deviation_reason gesetzt sein.';

CREATE INDEX IF NOT EXISTS idx_te_source_attributions_country ON te_source_attributions (country_id);

-- Seed: globale Provider (country_id IS NULL)
INSERT INTO te_source_attributions (te_label, te_url, country_id, canonical_provider, notes) VALUES
  ('Eurostat',                          'https://ec.europa.eu/eurostat',                NULL, 'eurostat',  'EU statistical office. Liefert HICP, IPP, Arbeitslosenrate (ILO), Industrieproduktion, BoP, GDP-Quartal etc. für alle EU-Mitgliedstaaten und EA-Aggregate.'),
  ('European Central Bank',             'https://www.ecb.europa.eu',                    NULL, 'ecb',       'ECB Statistical Data Warehouse (SDMX). Hauptsächlich Leitzinsen, M1/M2/M3, Bilanz, ULC, Wechselkurse.'),
  ('European Commission',               'https://commission.europa.eu',                 NULL, 'eurostat',  'DG ECFIN Business and Consumer Surveys (BSCI/BCI). Wir ziehen technisch via Eurostat (ei_bsin_m_r2, ei_bsco_m).'),
  ('World Bank',                        'https://data.worldbank.org',                   NULL, 'worldbank', 'World Development Indicators (jährlich). Hauptsächlich Tier-3-Daten wie population, gdp-per-capita-ppp.'),
  ('OECD',                              'https://data.oecd.org',                        NULL, 'curated',   'Selten verwendete OECD-Reihen (Hospital Beds, Doctors, Nurses). Wir laden als curated wenn keine alternative Quelle.'),
  ('Transparency International',        'https://www.transparency.org/en/cpi',          NULL, 'curated',   'Corruption Perceptions Index (jährlich). Wird als curated geladen.'),
  ('Vision of Humanity',                'https://www.visionofhumanity.org',             NULL, 'curated',   'Global Peace Index, Global Terrorism Index (jährlich). Curated.'),
  ('Fitch Ratings',                     'https://www.fitchratings.com',                 NULL, 'curated',   'Sovereign-Credit-Ratings. Curated.'),
  ('IATA',                              'https://www.iata.org',                         NULL, 'curated',   'Tourist-Arrivals / Air Passengers (selten genutzt). Curated.'),
  ('SIPRI',                             'https://www.sipri.org',                        NULL, 'curated',   'Military Expenditure (jährlich). Curated CSV-Download.'),
  ('Trading Economics',                 'https://tradingeconomics.com',                 NULL, 'curated',   'Fallback wenn TE eine Reihe selbst publiziert ohne Primärquelle (sehr selten).');

-- Seed: Nationale Behörden — pro Land, Provider und Standard-URL
WITH iso AS (SELECT country_id, code FROM countries)
INSERT INTO te_source_attributions (te_label, te_url, country_id, canonical_provider, notes)
SELECT v.te_label, v.te_url, iso.country_id, v.canonical_provider, v.notes
FROM iso
JOIN (VALUES
  -- US
  ('US', 'Federal Reserve',                          'https://www.federalreserve.gov',           'fred',         'Federal Reserve / FOMC. Wir ziehen via FRED (CPIAUCSL, UNRATE, FEDFUNDS, GFDEBTN, ...).'),
  ('US', 'U.S. Bureau of Labor Statistics',          'https://www.bls.gov',                       'fred',         'BLS via FRED-Spiegel. Inflation, Unemployment, NFP, Earnings, JOLTS.'),
  ('US', 'U.S. Bureau of Economic Analysis',         'https://www.bea.gov',                       'fred',         'BEA via FRED. GDP, PCE, Personal Income, Trade Balance.'),
  ('US', 'U.S. Census Bureau',                       'https://www.census.gov',                    'fred',         'Census via FRED. Building Permits, Retail Sales, Housing Starts, Trade.'),
  ('US', 'Federal Reserve Bank of Atlanta',          'https://www.atlantafed.org',                'fred',         'Wage Growth Tracker, GDPNow.'),
  ('US', 'Federal Reserve Bank of Chicago',          'https://www.chicagofed.org',                'fred',         'NFCI, CFNAI.'),
  ('US', 'U.S. Department of Labor',                 'https://www.dol.gov',                       'fred',         'Initial Jobless Claims (ICSA), Continuing Claims (CCSA).'),
  ('US', 'U.S. Energy Information Administration',   'https://www.eia.gov',                       'eia',          'EIA API: Crude Oil Production, Gasoline Inventories.'),
  ('US', 'U.S. Department of the Treasury',          'https://www.treasury.gov',                  'fred',         'Treasury Yields, Federal Debt, Government Budget Balance.'),
  ('US', 'National Federation of Independent Business','https://www.nfib.com',                    'curated',      'NFIB Small Business Optimism Index. Lizenz/Curated.'),
  ('US', 'Federal Housing Finance Agency',           'https://www.fhfa.gov',                      'fred',         'FHFA House Price Index.'),
  ('US', 'National Association of Realtors',         'https://www.nar.realtor',                   'fred',         'Existing Home Sales, Pending Home Sales.'),
  -- UK
  ('GB', 'Office for National Statistics',           'https://www.ons.gov.uk',                    'ons',          'ONS via Beta-API + CSV. CPI, RPI, GDP, Unemployment, Retail Sales, Trade.'),
  ('GB', 'Bank of England',                          'https://www.bankofengland.co.uk',           'ons',          'BoE IADB (über ons-Provider). Bank Rate, Reserves, Money Supply.'),
  ('GB', 'HM Treasury',                              'https://www.gov.uk/hm-treasury',            'curated',      'Government Budget Forecasts. Curated.'),
  ('GB', 'Halifax',                                  'https://www.halifax.co.uk',                 'curated',      'Halifax House Price Index. Curated.'),
  ('GB', 'Nationwide',                               'https://www.nationwide.co.uk',              'curated',      'Nationwide House Price Index. Curated.'),
  -- Germany
  ('DE', 'Deutsche Bundesbank',                      'https://www.bundesbank.de',                 'bundesbank',   'Bundesbank SDMX-API. Wechselkurse, Industrie-Indizes, Bauwesen, BoP, Mittelstand.'),
  ('DE', 'Statistisches Bundesamt',                  'https://www.destatis.de',                   'destatis',     'Destatis GENESIS-API via pystatis. CPI, PPI, Trade, Arbeitslosenzahl.'),
  ('DE', 'Federal Statistical Office',               'https://www.destatis.de',                   'destatis',     'Englischer Name; wird auf TE alternativ zu Destatis genutzt.'),
  ('DE', 'Federal Employment Agency',                'https://statistik.arbeitsagentur.de',       'curated',      'Bundesagentur für Arbeit. Aktuell curated bis API-Registration.'),
  ('DE', 'ifo Institut',                             'https://www.ifo.de',                        'curated',      'ifo Business Climate Index. Lizenz/Curated.'),
  ('DE', 'GfK',                                      'https://www.gfk.com',                       'curated',      'GfK Consumer Climate. Lizenz/Curated.'),
  ('DE', 'ZEW',                                      'https://www.zew.de',                        'curated',      'ZEW Indicator of Economic Sentiment. Lizenz/Curated.'),
  -- France
  ('FR', 'INSEE',                                    'https://www.insee.fr',                      'insee',        'Institut National de la Statistique. CPI, PPI, IP, Trade, GDP.'),
  ('FR', 'Banque de France',                         'https://www.banque-france.fr',              'bdf',          'BdF Webstat API. Foreign Reserves, Loans, Money Aggregates.'),
  ('FR', 'DARES',                                    'https://dares.travail-emploi.gouv.fr',      'curated',      'DARES Job Vacancies. Kein public API. Aktuell curated.'),
  -- Italy
  ('IT', 'Istituto Nazionale di Statistica',         'https://www.istat.it',                      'istat',        'ISTAT SDMX-API.'),
  ('IT', 'ISTAT',                                    'https://www.istat.it',                      'istat',        'Abkürzung.'),
  ('IT', 'Bank of Italy',                            'https://www.bancaditalia.it',               'curated',      'BoI Statistik (selten). Curated.'),
  -- Spain
  ('ES', 'Instituto Nacional de Estadistica',        'https://www.ine.es',                        'ine_es',       'INE Spain JSON-API.'),
  ('ES', 'INE',                                      'https://www.ine.es',                        'ine_es',       'Abkürzung.'),
  ('ES', 'Bank of Spain',                            'https://www.bde.es',                        'curated',      'Bde. Curated.'),
  -- Netherlands
  ('NL', 'Statistics Netherlands',                   'https://www.cbs.nl',                        'curated',      'CBS via OData4-API. TCP-Block aktuell; aktuell curated. Sebastian-TODO: VPN/Vercel-Proxy.'),
  ('NL', 'CBS Netherlands',                          'https://www.cbs.nl',                        'curated',      'Aliase.'),
  -- Belgium
  ('BE', 'Statbel',                                  'https://statbel.fgov.be',                   'national_eu',  'Statbel via national_eu-Provider.'),
  ('BE', 'National Bank of Belgium',                 'https://www.nbb.be',                        'national_eu',  'NBB BoP. Wir ziehen via national_eu-Provider.'),
  -- Austria
  ('AT', 'Statistics Austria',                       'https://www.statistik.at',                  'national_eu',  'Statistik Austria SDMX (stat_at via national_eu).'),
  ('AT', 'Federal Ministry of Finance',              'https://www.bmf.gv.at',                     'curated',      'BMF (Corporate-Tax-Rate etc.). Curated.'),
  ('AT', 'Austrian National Bank',                   'https://www.oenb.at',                       'curated',      'OeNB BoP. Curated.'),
  -- Portugal
  ('PT', 'Statistics Portugal',                      'https://www.ine.pt',                        'national_eu',  'INE Portugal SMI-API (national_eu).'),
  ('PT', 'Banco de Portugal',                        'https://www.bportugal.pt',                  'curated',      'BdP. Curated.'),
  -- Greece
  ('GR', 'National Statistical Service of Greece',   'https://www.statistics.gr',                 'elstat',       'ELSTAT SDMX-API.'),
  ('GR', 'ELSTAT',                                   'https://www.statistics.gr',                 'elstat',       'Abkürzung.'),
  ('GR', 'Bank of Greece',                           'https://www.bankofgreece.gr',               'curated',      'BoG. Curated.'),
  -- Ireland
  ('IE', 'Central Statistics Office Ireland',        'https://www.cso.ie',                        'national_eu',  'CSO via PxStat-API (national_eu).'),
  ('IE', 'CSO Ireland',                              'https://www.cso.ie',                        'national_eu',  'Abkürzung.'),
  -- Finland
  ('FI', 'Statistics Finland',                       'https://www.stat.fi',                       'national_eu',  'Statistics Finland PxWeb-API (national_eu).'),
  -- Luxembourg
  ('LU', 'Statec Luxembourg',                        'https://statistiques.public.lu',            'statec',       'STATEC lustat SDMX-API.'),
  ('LU', 'Central Bank of Luxembourg',               'https://www.bcl.lu',                        'statec',       'BCL via STATEC SDMX.'),
  -- Slovakia
  ('SK', 'Statistical Office of the Slovak Republic','https://slovak.statistics.sk',              'national_eu',  'SUSR PxWeb (national_eu).'),
  -- Slovenia
  ('SI', 'Statistical Office of Slovenia',           'https://www.stat.si',                       'national_eu',  'SURS PxWeb (national_eu).'),
  -- Estonia
  ('EE', 'Statistics Estonia',                       'https://www.stat.ee',                       'national_eu',  'Statistics Estonia PxWeb (national_eu).'),
  -- Latvia
  ('LV', 'Central Statistical Bureau of Latvia',     'https://www.csb.gov.lv',                    'national_eu',  'CSB Latvia PxWeb (national_eu).'),
  -- Lithuania
  ('LT', 'Statistics Lithuania',                     'https://www.lsd.lt',                        'lsd_lt',       'LSD via lsd_lt-Provider.'),
  -- Cyprus
  ('CY', 'Statistical Service of Cyprus',            'https://www.cystat.gov.cy',                 'national_eu',  'CySTAT PxWeb (national_eu).'),
  -- Malta
  ('MT', 'National Statistics Office Malta',         'https://nso.gov.mt',                        'national_eu',  'NSO Malta (national_eu).'),
  -- Poland
  ('PL', 'Statistics Poland',                        'https://stat.gov.pl',                       'gus_pl',       'GUS DBW-API (siehe memory/reference_gus_dbw_api).'),
  ('PL', 'GUS',                                      'https://stat.gov.pl',                       'gus_pl',       'Abkürzung.'),
  ('PL', 'National Bank of Poland',                  'https://www.nbp.pl',                        'gus_pl',       'NBP via GUS.'),
  -- Czech Republic
  ('CZ', 'Czech Statistical Office',                 'https://www.czso.cz',                       'czso',         'CZSO PxWeb (czso).'),
  -- Hungary
  ('HU', 'Hungarian Central Statistical Office',     'https://www.ksh.hu',                        'national_eu',  'KSH (national_eu).'),
  -- Romania
  ('RO', 'National Institute of Statistics Romania', 'https://insse.ro',                          'national_eu',  'INSSE TempoOnline (national_eu).'),
  -- Bulgaria
  ('BG', 'National Statistical Institute of Bulgaria','https://www.nsi.bg',                       'nsi_bg',       'NSI via nsi_bg.'),
  -- Croatia
  ('HR', 'Croatian Bureau of Statistics',            'https://dzs.gov.hr',                        'national_eu',  'DZS (national_eu).'),
  -- Denmark
  ('DK', 'Statistics Denmark',                       'https://www.dst.dk',                        'national_eu',  'Statbank PxAPI (national_eu).'),
  -- Sweden
  ('SE', 'Statistics Sweden',                        'https://www.scb.se',                        'national_eu',  'SCB PxWeb (national_eu).'),
  ('SE', 'Konjunkturinstitutet',                     'https://www.konj.se',                       'konj_se',      'NIER (konj_se).'),
  -- China
  ('CN', 'National Bureau of Statistics of China',   'http://www.stats.gov.cn',                   'akshare_cn',   'NBS via AkShare-Wrapper.'),
  ('CN', 'NBS',                                      'http://www.stats.gov.cn',                   'akshare_cn',   'Abkürzung.'),
  ('CN', 'Peoples Bank of China',                    'http://www.pbc.gov.cn',                     'akshare_cn',   'PBoC via AkShare.'),
  ('CN', 'General Administration of Customs',        'http://english.customs.gov.cn',             'gacc',         'GACC via custom provider.'),
  ('CN', 'Caixin',                                   'https://www.caixin.com',                    'curated',      'Caixin PMI. Lizenz/Curated.')
) AS v(country_code, te_label, te_url, canonical_provider, notes) ON v.country_code = iso.code
ON CONFLICT (te_label, country_id) DO NOTHING;
