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
  [x] akshare_cn     (Name: akshare + alias akshare_cn)
  [x] gacc
  [x] bdf
  [x] statec_lu
  [x] elstat
  [x] nsi_bg
  [x] czso
  [x] lsd_lt
  [x] konj_se
  [x] eia
  [x] curated
  [x] worldbank
  [x] ine_pt         (registered via national_eu_v2)
  [x] national_eu    (national_eu_v2.py: 17 BaseProvider-Subklassen unter den jeweiligen DB-Provider-Namen
                      stat_at/statbel/cso_ie/stat_fi/susr_sk/surs_si/stat_ee/csp_lv/cystat_cy/nso_mt/
                      scb_se/dst/dzs_hr/ksh_hu/insse_ro/nbb/ine_pt)
  [x] riksbank       (SE policy rate — Riksbank SweaWS REST)
  [x] nationalbanken (DK discount rate — Danmarks Nationalbank Statbank CSV)
  [x] mnb            (HU base rate — MNB alapkamat.xlsx)
  [x] cnb            (CZ 2W repo rate — CNB FAQ TXT)
  [s] nbp            (PL — STUB; NBP page JS-rendered)
  [s] bnr            (RO — STUB; BNR page JS-rendered)
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
from pipeline.providers import akshare_cn   # noqa: F401
from pipeline.providers import gacc         # noqa: F401
from pipeline.providers import bdf          # noqa: F401
from pipeline.providers import elstat       # noqa: F401
from pipeline.providers import nsi_bg       # noqa: F401
from pipeline.providers import czso         # noqa: F401
from pipeline.providers import lsd_lt       # noqa: F401
from pipeline.providers import konj_se      # noqa: F401
from pipeline.providers import national_eu_v2  # noqa: F401  (registriert 17 Sub-Provider)

# Phase C: central-bank policy-rate providers (interest-rate gaps)
from pipeline.providers import riksbank        # noqa: F401  (SE)
from pipeline.providers import nationalbanken  # noqa: F401  (DK)
from pipeline.providers import mnb             # noqa: F401  (HU)
from pipeline.providers import cnb             # noqa: F401  (CZ)
from pipeline.providers import nbp             # noqa: F401  (PL — STUB)
from pipeline.providers import bnr             # noqa: F401  (RO — STUB)
