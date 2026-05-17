"""Provider-Registry.

Importiert alle migrierten V2-Provider, sodass deren Self-Registration
beim Dispatcher-Import ausgeführt wird.

Migrations-Status (V2-stateless via fetch_series):
  [x] fred
  [x] eurostat
  [x] ecb
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
  [x] eia
  [x] curated
  [x] worldbank
  [ ] national_eu    (pending, dispatches stat_at/statbel/cso_ie/.../scb_se/dst/dzs_hr/ksh_hu/insse_ro/nbb)
"""
from pipeline.providers import fred       # noqa: F401
from pipeline.providers import eurostat   # noqa: F401
from pipeline.providers import ecb        # noqa: F401
from pipeline.providers import worldbank  # noqa: F401
from pipeline.providers import curated    # noqa: F401
from pipeline.providers import eia        # noqa: F401
