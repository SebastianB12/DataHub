-- Seed indicator_sources rows for the existing hardcoded Eurostat SERIES list.
-- Each (indicator, country) gets one row with extra_params.dataset + extra_params.params.
-- The refactored eurostat.py groups rows by (dataset, params) and fetches once per group
-- with the union of needed geos.
--
-- All seeded rows are flagged is_default=true. For (indicator, country) pairs where another
-- provider (destatis, bundesbank, ons, fred, ecb, ...) is also active, the override happens
-- in subsequent migrations / DB ops by setting is_default=false on these eurostat rows.

INSERT INTO indicator_sources (indicator, country, source, series_id, transform, conversion, unit, adjustment, freq_hint, extra_params, is_default, note) VALUES
  -- ============== GDP & Growth (namq_10_gdp) ==============
  -- gdp-growth dropped 2026-04-30: derived in frontend from gdp-real via Display-Toggle.
  ('gdp-real',   'EA', 'eurostat', 'namq_10_gdp:CLV10_MEUR', 'raw', 0.001, 'Billion EUR', 'SA', 'Q',
    '{"dataset":"namq_10_gdp","params":{"na_item":"B1GQ","unit":"CLV10_MEUR","s_adj":"SCA"}}', true,
    'Real GDP, chained vols, M EUR -> B EUR'),
  ('gdp-real',   'DE', 'eurostat', 'namq_10_gdp:CLV10_MEUR', 'raw', 0.001, 'Billion EUR', 'SA', 'Q',
    '{"dataset":"namq_10_gdp","params":{"na_item":"B1GQ","unit":"CLV10_MEUR","s_adj":"SCA"}}', true, NULL),

  -- ============== Inflation (ei_cphi_m, Flash HICP) ==============
  ('inflation-cpi', 'EA', 'eurostat', 'ei_cphi_m:TOTAL', 'raw', 1, 'Index', 'NSA', 'M',
    '{"dataset":"ei_cphi_m","params":{"indic":"TOTAL","unit":"HICP2025"}}', true, 'Flash HICP'),
  ('inflation-cpi', 'DE', 'eurostat', 'ei_cphi_m:TOTAL', 'raw', 1, 'Index', 'NSA', 'M',
    '{"dataset":"ei_cphi_m","params":{"indic":"TOTAL","unit":"HICP2025"}}', false, 'Destatis primary; eurostat fallback'),
  ('inflation-cpi', 'GB', 'eurostat', 'ei_cphi_m:TOTAL', 'raw', 1, 'Index', 'NSA', 'M',
    '{"dataset":"ei_cphi_m","params":{"indic":"TOTAL","unit":"HICP2025"}}', false, 'ONS primary; eurostat fallback'),

  ('core-cpi', 'EA', 'eurostat', 'ei_cphi_m:CP-HI00XEF', 'raw', 1, 'Index', 'NSA', 'M',
    '{"dataset":"ei_cphi_m","params":{"indic":"CP-HI00XEF","unit":"HICP2025"}}', true, 'Flash core HICP'),
  ('core-cpi', 'DE', 'eurostat', 'ei_cphi_m:CP-HI00XEF', 'raw', 1, 'Index', 'NSA', 'M',
    '{"dataset":"ei_cphi_m","params":{"indic":"CP-HI00XEF","unit":"HICP2025"}}', true, NULL),
  ('core-cpi', 'GB', 'eurostat', 'ei_cphi_m:CP-HI00XEF', 'raw', 1, 'Index', 'NSA', 'M',
    '{"dataset":"ei_cphi_m","params":{"indic":"CP-HI00XEF","unit":"HICP2025"}}', true, NULL),

  -- ============== PPI (sts_inppd_m) ==============
  ('ppi', 'EA', 'eurostat', 'sts_inppd_m:B-D', 'raw', 1, 'Index', 'NSA', 'M',
    '{"dataset":"sts_inppd_m","params":{"nace_r2":"B-D","unit":"I21","s_adj":"NSA"}}', true, NULL),
  ('ppi', 'DE', 'eurostat', 'sts_inppd_m:B-D', 'raw', 1, 'Index', 'NSA', 'M',
    '{"dataset":"sts_inppd_m","params":{"nace_r2":"B-D","unit":"I21","s_adj":"NSA"}}', false, 'Destatis primary; eurostat fallback'),

  -- ============== Unemployment (ei_lmhr_m, Flash) ==============
  ('unemployment', 'EA', 'eurostat', 'ei_lmhr_m:LM-UN-T-TOT', 'raw', 1, '%', 'SA', 'M',
    '{"dataset":"ei_lmhr_m","params":{"indic":"LM-UN-T-TOT","unit":"PC_ACT","s_adj":"SA"}}', true, NULL),
  ('unemployment', 'DE', 'eurostat', 'ei_lmhr_m:LM-UN-T-TOT', 'raw', 1, '%', 'SA', 'M',
    '{"dataset":"ei_lmhr_m","params":{"indic":"LM-UN-T-TOT","unit":"PC_ACT","s_adj":"SA"}}', false, 'Destatis primary'),
  ('unemployment', 'GB', 'eurostat', 'ei_lmhr_m:LM-UN-T-TOT', 'raw', 1, '%', 'SA', 'M',
    '{"dataset":"ei_lmhr_m","params":{"indic":"LM-UN-T-TOT","unit":"PC_ACT","s_adj":"SA"}}', false, 'UK ends ~2020 (Brexit); ONS primary'),

  -- ============== Employment Rate (lfsa_ergan, annual) ==============
  ('employment-rate', 'EA', 'eurostat', 'lfsa_ergan:Y20-64', 'raw', 1, '%', '', 'A',
    '{"dataset":"lfsa_ergan","params":{"age":"Y20-64","sex":"T","unit":"PC","citizen":"TOTAL"}}', true, NULL),
  ('employment-rate', 'DE', 'eurostat', 'lfsa_ergan:Y20-64', 'raw', 1, '%', '', 'A',
    '{"dataset":"lfsa_ergan","params":{"age":"Y20-64","sex":"T","unit":"PC","citizen":"TOTAL"}}', true, NULL),
  ('employment-rate', 'GB', 'eurostat', 'lfsa_ergan:Y20-64', 'raw', 1, '%', '', 'A',
    '{"dataset":"lfsa_ergan","params":{"age":"Y20-64","sex":"T","unit":"PC","citizen":"TOTAL"}}', false, 'ONS primary'),

  -- ============== Population (demo_pjan) ==============
  ('population', 'EA', 'eurostat', 'demo_pjan:TOTAL', 'raw', 0.000001, 'Millions', '', 'A',
    '{"dataset":"demo_pjan","params":{"age":"TOTAL","sex":"T"}}', true, 'Persons -> Millions'),
  ('population', 'DE', 'eurostat', 'demo_pjan:TOTAL', 'raw', 0.000001, 'Millions', '', 'A',
    '{"dataset":"demo_pjan","params":{"age":"TOTAL","sex":"T"}}', true, NULL),
  ('population', 'GB', 'eurostat', 'demo_pjan:TOTAL', 'raw', 0.000001, 'Millions', '', 'A',
    '{"dataset":"demo_pjan","params":{"age":"TOTAL","sex":"T"}}', true, NULL),

  -- ============== Trade (nama_10_exi, annual) ==============
  ('exports', 'EA', 'eurostat', 'nama_10_exi:P6', 'raw', 0.001, 'Billion EUR', '', 'A',
    '{"dataset":"nama_10_exi","params":{"na_item":"P6","unit":"CP_MEUR"}}', true, 'Annual; monthly preferred where available'),
  ('exports', 'DE', 'eurostat', 'nama_10_exi:P6', 'raw', 0.001, 'Billion EUR', '', 'A',
    '{"dataset":"nama_10_exi","params":{"na_item":"P6","unit":"CP_MEUR"}}', false, 'Destatis monthly primary'),
  ('exports', 'GB', 'eurostat', 'nama_10_exi:P6', 'raw', 0.001, 'Billion EUR', '', 'A',
    '{"dataset":"nama_10_exi","params":{"na_item":"P6","unit":"CP_MEUR"}}', false, 'ONS monthly primary'),

  ('imports', 'EA', 'eurostat', 'nama_10_exi:P7', 'raw', 0.001, 'Billion EUR', '', 'A',
    '{"dataset":"nama_10_exi","params":{"na_item":"P7","unit":"CP_MEUR"}}', true, NULL),
  ('imports', 'DE', 'eurostat', 'nama_10_exi:P7', 'raw', 0.001, 'Billion EUR', '', 'A',
    '{"dataset":"nama_10_exi","params":{"na_item":"P7","unit":"CP_MEUR"}}', false, 'Destatis monthly primary'),
  ('imports', 'GB', 'eurostat', 'nama_10_exi:P7', 'raw', 0.001, 'Billion EUR', '', 'A',
    '{"dataset":"nama_10_exi","params":{"na_item":"P7","unit":"CP_MEUR"}}', false, 'ONS monthly primary'),

  -- ============== Current Account (different datasets per geo) ==============
  ('current-account', 'DE', 'eurostat', 'bop_c6_q:CA', 'raw', 0.001, 'Billion EUR', '', 'Q',
    '{"dataset":"bop_c6_q","params":{"bop_item":"CA","stk_flow":"BAL","currency":"MIO_EUR","partner":"WRL_REST"},"geo_override":["DE"]}',
    true, 'Bundesbank primary; eurostat fallback'),
  ('current-account', 'EA', 'eurostat', 'bop_eu6_q:CA', 'raw', 0.001, 'Billion EUR', '', 'Q',
    '{"dataset":"bop_eu6_q","params":{"bop_item":"CA","stk_flow":"BAL","currency":"MIO_EUR","partner":"EXT_EA20","sector10":"S1","sectpart":"S1"},"geo_override":["EA20"]}',
    true, 'EA aggregate, extra-EA partner'),

  -- ============== Government (gov_10dd_edpt1, annual) ==============
  ('budget-deficit', 'EA', 'eurostat', 'gov_10dd_edpt1:B9', 'raw', 1, '% of GDP', '', 'A',
    '{"dataset":"gov_10dd_edpt1","params":{"na_item":"B9","unit":"PC_GDP","sector":"S13"}}', true, NULL),
  ('budget-deficit', 'DE', 'eurostat', 'gov_10dd_edpt1:B9', 'raw', 1, '% of GDP', '', 'A',
    '{"dataset":"gov_10dd_edpt1","params":{"na_item":"B9","unit":"PC_GDP","sector":"S13"}}', true, NULL),
  ('budget-deficit', 'GB', 'eurostat', 'gov_10dd_edpt1:B9', 'raw', 1, '% of GDP', '', 'A',
    '{"dataset":"gov_10dd_edpt1","params":{"na_item":"B9","unit":"PC_GDP","sector":"S13"}}', false, 'ONS primary'),

  ('government-debt', 'EA', 'eurostat', 'gov_10dd_edpt1:GD', 'raw', 1, '% of GDP', '', 'A',
    '{"dataset":"gov_10dd_edpt1","params":{"na_item":"GD","unit":"PC_GDP","sector":"S13"}}', true, NULL),
  ('government-debt', 'DE', 'eurostat', 'gov_10dd_edpt1:GD', 'raw', 1, '% of GDP', '', 'A',
    '{"dataset":"gov_10dd_edpt1","params":{"na_item":"GD","unit":"PC_GDP","sector":"S13"}}', true, NULL),
  ('government-debt', 'GB', 'eurostat', 'gov_10dd_edpt1:GD', 'raw', 1, '% of GDP', '', 'A',
    '{"dataset":"gov_10dd_edpt1","params":{"na_item":"GD","unit":"PC_GDP","sector":"S13"}}', false, 'ONS primary')
ON CONFLICT (indicator, country, source, series_id) DO NOTHING;
