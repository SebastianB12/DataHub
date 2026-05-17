"""Provider-Registry.

Importiert alle migrierten V2-Provider, sodass deren Self-Registration
beim Dispatcher-Import ausgeführt wird.

Migrations-Status (V2-stateless via fetch_series):
  [x] fred
  [x] eurostat
  [x] ecb
  [x] ons
  [x] bundesbank
  [x] destatis
  [x] insee
  [x] istat
  [x] ine_es
  [x] gus_pl
  [ ] akshare_cn     (Welle 4)
  [ ] gacc           (Welle 4)
  [ ] bdf            (Welle 4)
  [x] statec_lu
  [ ] elstat         (pending)
  [ ] nsi_bg         (pending)
  [ ] czso           (pending)
  [ ] lsd_lt         (pending)
  [ ] konj_se        (pending)
  [x] eia
  [x] curated
  [x] worldbank
  [ ] ine_pt         (pending; auth needed)
  [ ] national_eu    (pending, dispatches stat_at/statbel/cso_ie/.../scb_se/dst/dzs_hr/ksh_hu/insse_ro/nbb)
"""
from pipeline.providers import fred         # noqa: F401
from pipeline.providers import eurostat     # noqa: F401
from pipeline.providers import ecb          # noqa: F401
from pipeline.providers import worldbank    # noqa: F401
from pipeline.providers import curated      # noqa: F401
from pipeline.providers import eia          # noqa: F401
from pipeline.providers import ons          # noqa: F401
from pipeline.providers import bundesbank   # noqa: F401
from pipeline.providers import destatis     # noqa: F401
from pipeline.providers import insee        # noqa: F401
from pipeline.providers import istat        # noqa: F401
from pipeline.providers import ine_es       # noqa: F401
from pipeline.providers import gus_pl       # noqa: F401
from pipeline.providers import statec       # noqa: F401
