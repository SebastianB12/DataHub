"""Provider-Registry.

Importiert alle migrierten V2-Provider, sodass deren Self-Registration
beim Dispatcher-Import ausgeführt wird.

Migrations-Status (V2-stateless via fetch_series):
  [x] fred
  [ ] eurostat       (pending)
  [ ] ecb            (pending)
  [ ] ons            (pending)
  [ ] bundesbank     (pending)
  [ ] destatis       (pending)
  [ ] insee          (pending)
  [ ] istat          (pending)
  [ ] ine_es         (pending)
  [ ] gus_pl         (pending)
  [ ] akshare_cn     (pending)
  [ ] gacc           (pending)
  [ ] bdf            (pending)
  [ ] statec         (pending)
  [ ] elstat         (pending)
  [ ] nsi_bg         (pending)
  [ ] czso           (pending)
  [ ] lsd_lt         (pending)
  [ ] konj_se        (pending)
  [ ] eia            (pending)
  [ ] curated        (pending)
  [ ] worldbank      (pending)
  [ ] national_eu    (pending, dispatches stat_at/statbel/cso_ie/.../scb_se/dst/dzs_hr/ksh_hu/insse_ro/nbb)
"""
from pipeline.providers import fred  # noqa: F401
