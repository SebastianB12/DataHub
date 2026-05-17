-- Migration 089: Display-Toggle-Architektur an indicator_families.
--
-- Hintergrund: Bisher hatte jede Family genau ein default_te_display_transform
-- (z.B. yoy_pct für CPI). Frontend rechnete YoY/MoM/QoQ jeweils aus dem rohen
-- value_kind in data_series ab — aber nur stillschweigend.
--
-- Pivot: Eine Family = eine echte Datenreihe (raw level wo Source ihn anbietet).
-- Display-Modi (Index / YoY% / MoM% / QoQ%) sind Frontend-View-Logik. Diese
-- Migration deklariert pro Family WELCHE Modi zulässig sind und welcher Default
-- beim Page-Load aktiv ist.
--
-- available_displays: array aus {level, yoy_pct, mom_pct, qoq_pct}.
-- default_display:    eines davon — was die TE-Page als headline-Zahl zeigt.

ALTER TABLE indicator_families
  ADD COLUMN IF NOT EXISTS available_displays TEXT[] NOT NULL DEFAULT ARRAY['level'],
  ADD COLUMN IF NOT EXISTS default_display    TEXT   NOT NULL DEFAULT 'level';

COMMENT ON COLUMN indicator_families.available_displays IS 'Welche Display-Modi das Frontend für diese Family rendert. Subset von {level, yoy_pct, mom_pct, qoq_pct}.';
COMMENT ON COLUMN indicator_families.default_display    IS 'Welcher Display-Mode beim Page-Load aktiv ist. Identisch zu dem, was TE als headline-Zahl zeigt. Muss in available_displays enthalten sein.';

-- Backfill: bestehende default_te_display_transform → default_display kopieren,
-- damit nichts kaputt geht wo die alte Spalte schon korrekt gesetzt war.
UPDATE indicator_families
   SET default_display = default_te_display_transform
 WHERE default_te_display_transform IS NOT NULL
   AND default_te_display_transform IN ('level','yoy_pct','mom_pct','qoq_pct');

-- Setup der 4 Core-Families (Phase A.2 aus rosy-dancing-pond.md).
-- Hinweis: family_code 'gdp' (family_id=4) ist aktuell die Annual-Nominal-World-Bank-Reihe
-- und wird in Phase B gelöscht. Family 'gdp-real' (family_id=3) wird in Phase B umbenannt
-- auf family_code='gdp' und enthält dann Quarterly Real GDP Level.
-- Wir setzen die Display-Konfiguration hier bereits an family_code='gdp-real',
-- damit nach dem Rename in Phase B keine zweite UPDATE-Runde nötig ist.

UPDATE indicator_families
   SET default_display    = 'yoy_pct',
       available_displays = ARRAY['level','yoy_pct','mom_pct']
 WHERE family_code = 'inflation-cpi';

UPDATE indicator_families
   SET default_display    = 'qoq_pct',
       available_displays = ARRAY['level','yoy_pct','qoq_pct']
 WHERE family_code = 'gdp-real';

UPDATE indicator_families
   SET default_display    = 'level',
       available_displays = ARRAY['level']
 WHERE family_code IN ('unemployment','interest-rate');
