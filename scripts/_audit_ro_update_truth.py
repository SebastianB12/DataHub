# -*- coding: utf-8 -*-
"""Update RO block in docs/te_sources_truth.yaml with re-audit results.

Loads the file as text, finds the RO: ... <next-key>: block, replaces it
with the new RO block. Preserves the rest of the file byte-for-byte.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRUTH = ROOT / "docs" / "te_sources_truth.yaml"

NEW_RO_BLOCK = """RO:
  # Re-audit 2026-05-17 (mig 078_ro_reaudit): all 68 RO slugs verified against
  # fresh TE fetches (see docs/_audit_ro_reaudit.yaml). Honest-label rule:
  # source = technical fetch source (eurostat/ecb/insse_ro/worldbank/curated),
  # never relabeled as upstream TE attribution.
  budget-deficit:
    note: 'gap: TE attributes Ministerul Finantelor Publice (MFP). We serve
      Eurostat gov_10dd_edpt1 (% of GDP) as fallback. Future work: MFP RO provider.'
    source: eurostat
    te_label: Ministerul Finantelor Publice
    te_page: https://tradingeconomics.com/romania/government-budget
    verified: true
  business-confidence:
    source: eurostat
    te_label: European Commission
    te_page: https://tradingeconomics.com/romania/business-confidence
    te_url: http://ec.europa.eu
    verified: true
  capacity-utilization:
    source: eurostat
    te_label: European Commission
    te_page: https://tradingeconomics.com/romania/capacity-utilization
    verified: true
  changes-in-inventories:
    note: 'gap: TE attributes INSSE; we use Eurostat namq_10_gdp (P52) fallback.
      Future work: INSSE national-accounts series in RO_SERIES.'
    source: eurostat
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/changes-in-inventories
    verified: true
  consumer-confidence:
    source: eurostat
    te_label: European Commission
    te_page: https://tradingeconomics.com/romania/consumer-confidence
    te_url: http://ec.europa.eu
    verified: true
  consumer-spending:
    note: 'gap: TE displays INSSE quarterly final consumption in RON Million levels.
      We serve Eurostat namq_10_gdp aggregate (% / index). Future work: INSSE Tempo
      national-accounts.'
    source: eurostat
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/consumer-spending
    verified: true
  core-cpi:
    source: eurostat
    te_label: EUROSTAT
    te_page: https://tradingeconomics.com/romania/core-inflation-rate
    verified: true
  corporate-tax-rate:
    source: curated
    te_label: National Agency for Fiscal Administration (ANAF)
    te_page: https://tradingeconomics.com/romania/corporate-tax-rate
    verified: true
  corruption-index:
    source: curated
    te_label: Transparency International
    te_page: https://tradingeconomics.com/romania/corruption-index
    verified: true
  corruption-rank:
    source: curated
    te_label: Transparency International
    te_page: https://tradingeconomics.com/romania/corruption-rank
    verified: true
  cpi-clothing:
    note: 'no slug-specific TE page (returns generic homepage). Eurostat HICP
      COICOP CP03 retained.'
    source: eurostat
    te_page: https://tradingeconomics.com/romania/cpi-clothing
    verified: true
  cpi-education:
    note: 'no slug-specific TE page. Eurostat HICP CP10 retained.'
    source: eurostat
    te_page: https://tradingeconomics.com/romania/cpi-education
    verified: true
  cpi-food:
    note: 'no slug-specific TE page. Eurostat HICP CP01 retained.'
    source: eurostat
    te_page: https://tradingeconomics.com/romania/cpi-food
    verified: true
  cpi-housing-utilities:
    note: 'no slug-specific TE page. Eurostat HICP CP04 retained.'
    source: eurostat
    te_page: https://tradingeconomics.com/romania/cpi-housing-utilities
    verified: true
  cpi-recreation-and-culture:
    note: 'no slug-specific TE page. Eurostat HICP CP09 retained.'
    source: eurostat
    te_page: https://tradingeconomics.com/romania/cpi-recreation-and-culture
    verified: true
  cpi-transportation:
    source: eurostat
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/cpi-transportation
    verified: true
  credit-rating:
    note: 'no slug-specific TE page; manually curated rating composite.'
    source: curated
    te_page: https://tradingeconomics.com/romania/rating
    verified: true
  current-account:
    note: 'TE attributes Banca Nationala a Romaniei (BNR). We fetch ECB SDMX BoP
      which sources from BNR upstream. Honest fetch-source label = ecb.'
    source: ecb
    te_label: National Bank of Romania
    te_page: https://tradingeconomics.com/romania/current-account
    te_url: https://www.bnr.ro/
    verified: true
  current-account-to-gdp:
    note: 'gap: TE attributes MFP. Eurostat tipsbp20 fallback.'
    source: eurostat
    te_label: Ministerul Finantelor Publice
    te_page: https://tradingeconomics.com/romania/current-account-to-gdp
    verified: true
  disposable-personal-income:
    note: 'no slug-specific TE page; Eurostat nasq_10_nf_tr fallback.'
    source: eurostat
    te_page: https://tradingeconomics.com/romania/disposable-personal-income
    verified: true
  employed-persons:
    note: 'gap: TE = INSSE quarterly employment count (~5121k Q4 2025); we serve
      Eurostat LFS lfsi_emp_q (7579k). Different concept (LFS vs INSSE national).'
    source: eurostat
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/employed-persons
    verified: true
  employment-rate:
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/employment-rate
    te_url: https://insse.ro/cms/
    verified: true
  energy-inflation:
    note: 'no slug-specific TE page. Eurostat HICP energy retained.'
    source: eurostat
    te_page: https://tradingeconomics.com/romania/energy-inflation
    verified: true
  exports:
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/exports
    verified: true
  food-inflation:
    source: eurostat
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/food-inflation
    verified: true
  gdp:
    source: worldbank
    te_label: World Bank
    te_page: https://tradingeconomics.com/romania/gdp
    te_url: https://www.worldbank.org/
    verified: true
  gdp-per-capita:
    source: worldbank
    te_label: World Bank
    te_page: https://tradingeconomics.com/romania/gdp-per-capita
    te_url: https://www.worldbank.org/
    verified: true
  gdp-per-capita-ppp:
    source: worldbank
    te_label: World Bank
    te_page: https://tradingeconomics.com/romania/gdp-per-capita-ppp
    te_url: https://www.worldbank.org/
    verified: true
  gdp-real:
    note: 'gap: TE attributes INSSE; we use Eurostat namq_10_gdp fallback.'
    source: eurostat
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/gdp-growth-annual
    te_url: http://www.insse.ro/
    verified: true
  government-debt:
    note: 'gap: TE attributes MFP (% of GDP). Eurostat gov_10dd_edpt1 fallback.'
    source: eurostat
    te_label: Ministry of Public Finance, Romania
    te_page: https://tradingeconomics.com/romania/government-debt-to-gdp
    verified: true
  government-debt-total:
    note: 'gap: TE displays MFP RON Million absolute (~1.24M RON mn). Eurostat
      gov_10dd_edpt1 percent of GDP fallback (unit mismatch). Future work: MFP RO
      provider.'
    source: eurostat
    te_label: Ministry of Public Finance, Romania
    te_page: https://tradingeconomics.com/romania/government-debt
    verified: true
  government-spending:
    note: 'gap: TE = INSSE quarterly RON Million level; we serve Eurostat namq_10_gdp
      (% / index). Future work: INSSE Tempo CON national-accounts.'
    source: eurostat
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/government-spending
    verified: true
  government-spending-eur:
    note: 'gap: TE only publishes RON-Million quarterly under /government-spending;
      no separate EUR slug. Eurostat fallback retained.'
    source: eurostat
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/government-spending
    verified: true
  gross-fixed-capital-formation:
    note: 'gap: TE = INSSE RON-Million quarterly level (P51G ~78k RON mn); we use
      Eurostat namq_10_gdp ratio/index fallback.'
    source: eurostat
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/gross-fixed-capital-formation
    verified: true
  hospital-beds:
    note: 'no slug-specific TE page; curated WHO/Eurostat composite.'
    source: curated
    te_page: https://tradingeconomics.com/romania/hospital-beds
    verified: true
  house-price-index:
    source: eurostat
    te_label: EUROSTAT
    te_page: https://tradingeconomics.com/romania/housing-index
    te_url: https://ec.europa.eu/eurostat/
    verified: true
  imports:
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/imports
    te_url: http://www.insse.ro
    verified: true
  industrial-production:
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/industrial-production
    verified: true
  inflation-cpi:
    note: 'INSSE Tempo IPC102E CPI YoY index (same month prev year = 100). Value
      109.5 reads as TE headline 9.5% YoY. Provider uses row_filter exact TOTAL.'
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/inflation-cpi
    verified: true
  job-vacancies:
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/job-vacancies
    te_url: https://insse.ro/cms/
    verified: true
  labor-force-participation-rate:
    source: eurostat
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/labor-force-participation-rate
    te_url: https://insse.ro/cms/ro
    verified: true
  labour-costs:
    source: eurostat
    te_label: EUROSTAT
    te_page: https://tradingeconomics.com/romania/labour-costs
    verified: true
  long-term-unemployment-rate:
    source: eurostat
    te_label: EUROSTAT
    te_page: https://tradingeconomics.com/romania/long-term-unemployment-rate
    verified: true
  manufacturing-production:
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/manufacturing-production
    te_url: https://insse.ro/cms/
    verified: true
  medical-doctors:
    note: 'no slug-specific TE page; curated WHO/Eurostat composite.'
    source: curated
    te_page: https://tradingeconomics.com/romania/medical-doctors
    verified: true
  minimum-wages:
    note: 'Migrated 2026-05-17 (mig 078): curated -> eurostat earn_mw_cur (geo=RO,
      EUR, bi-annual). TE attributes EUROSTAT directly.'
    source: eurostat
    te_label: EUROSTAT
    te_page: https://tradingeconomics.com/romania/minimum-wages
    te_url: https://ec.europa.eu/eurostat/
    verified: true
  mining-production:
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/mining-production
    te_url: https://insse.ro/cms/
    verified: true
  nurses:
    note: 'no slug-specific TE page; curated WHO composite.'
    source: curated
    te_page: https://tradingeconomics.com/romania/nurses
    verified: true
  personal-income-tax-rate:
    source: curated
    te_label: National Agency for Fiscal Administration (ANAF)
    te_page: https://tradingeconomics.com/romania/personal-income-tax-rate
    verified: true
  population:
    source: eurostat
    te_label: EUROSTAT
    te_page: https://tradingeconomics.com/romania/population
    te_url: https://ec.europa.eu/eurostat/
    verified: true
  ppi:
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/producer-prices
    verified: true
  productivity:
    source: eurostat
    te_label: EUROSTAT
    te_page: https://tradingeconomics.com/romania/productivity
    te_url: https://ec.europa.eu/eurostat/
    verified: true
  retail-sales:
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/retail-sales
    te_url: http://www.insse.ro
    verified: true
  retirement-age-men:
    source: curated
    te_label: National Revenue Agency
    te_page: https://tradingeconomics.com/romania/retirement-age-men
    te_url: https://www.cnpp.ro
    verified: true
  retirement-age-women:
    source: curated
    te_label: National Revenue Agency
    te_page: https://tradingeconomics.com/romania/retirement-age-women
    te_url: https://www.cnpp.ro
    verified: true
  sales-tax-rate:
    source: curated
    te_label: National Agency for Fiscal Administration (ANAF)
    te_page: https://tradingeconomics.com/romania/sales-tax-rate
    te_url: https://www.vatlive.com
    verified: true
  services-inflation:
    note: 'no slug-specific TE page; Eurostat HICP services retained.'
    source: eurostat
    te_page: https://tradingeconomics.com/romania/services-inflation
    verified: true
  services-sentiment:
    note: 'no slug-specific TE page; Eurostat EU-Commission services-confidence
      retained.'
    source: eurostat
    te_page: https://tradingeconomics.com/romania/services-sentiment
    verified: true
  social-security-rate:
    source: curated
    te_label: Ministry of Labor, Family, and Social Protection
    te_page: https://tradingeconomics.com/romania/social-security-rate
    te_url: https://home.kpmg.com
    verified: true
  social-security-rate-companies:
    source: curated
    te_label: Ministry of Labor, Family, and Social Protection
    te_page: https://tradingeconomics.com/romania/social-security-rate-for-companies
    verified: true
  social-security-rate-employees:
    source: curated
    te_label: Ministry of Labor, Family, and Social Protection
    te_page: https://tradingeconomics.com/romania/social-security-rate-for-employees
    verified: true
  terrorism-index:
    source: curated
    te_label: Institute for Economics and Peace
    te_page: https://tradingeconomics.com/romania/terrorism-index
    verified: true
  trade-balance:
    note: 'Computed inside RO INSSE provider as exports - imports.'
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/balance-of-trade
    verified: true
  unemployed-persons:
    note: 'gap: TE = ANOFM (Agentia Nationala pentru Ocuparea Fortei de Munca)
      registered count; we serve Eurostat LFS une_rt_m (504k vs ANOFM 260k).
      Different concepts. Future work: scrape ANOFM monthly bulletin.'
    source: eurostat
    te_label: ANOFM, Romania
    te_page: https://tradingeconomics.com/romania/unemployed-persons
    verified: true
  unemployment:
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/unemployment-rate
    te_url: http://www.insse.ro
    verified: true
  unemployment-rate-registered:
    note: 'no slug-specific TE page; INSSE Tempo SOM103B registered unemployment
      rate retained.'
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/unemployment-rate
    te_url: http://www.insse.ro
    verified: true
  wages:
    source: insse_ro
    te_label: Institutul National de Statistica
    te_page: https://tradingeconomics.com/romania/wages
    te_url: https://insse.ro/cms/
    verified: true
  youth-unemployment-rate:
    source: eurostat
    te_label: EUROSTAT
    te_page: https://tradingeconomics.com/romania/youth-unemployment-rate
    verified: true
"""


def main() -> None:
    text = TRUTH.read_text(encoding="utf-8")
    # Find start of RO block: a line that is exactly "RO:" at column 0
    lines = text.splitlines(keepends=True)
    start = None
    end = None
    for i, line in enumerate(lines):
        if line.rstrip("\r\n") == "RO:":
            start = i
            continue
        if start is not None and line and line[0].isalpha() and ":" in line and not line.startswith(" "):
            end = i
            break
    if start is None:
        raise SystemExit("Could not find 'RO:' top-level key")
    if end is None:
        end = len(lines)
    print(f"Replacing lines {start+1}..{end} with new RO block ({len(NEW_RO_BLOCK.splitlines())} lines)")
    new_text = "".join(lines[:start]) + NEW_RO_BLOCK + "".join(lines[end:])
    TRUTH.write_text(new_text, encoding="utf-8")
    print("Wrote", TRUTH)


if __name__ == "__main__":
    main()
