/**
 * Source-Label-Resolver — wandelt unsere internen `source`-Codes (`fred`, `akshare`, …)
 * in nutzerseitige Labels um.
 *
 * Hard rule: Daten-Source = Anzeige-Source. Wenn die Daten via Eurostat reinkommen,
 * steht „Eurostat" da. Wenn sie via INSEE reinkommen, steht „INSEE" da. Es gibt
 * KEIN country-abhängiges Override. Wenn ein Label falsch wirkt, ist die Lösung
 * immer: eigenen Fetch von der TE-genannten Primärquelle bauen — niemals das
 * Label anders mappen als die tatsächliche Datenherkunft.
 *
 * Bei Aggregator-Quellen wie AkShare wechselt die Upstream-Quelle pro Reihe (NBS,
 * PBoC, GACC, SAFE, …). Wir lesen das aus dem `series_id` ab, weil AkShare aus
 * Sicht der DB nur ein Wrapper ist und wir die echten Endpoints im series_id
 * (z.B. `akshare:macro_china_lpr:LPR1Y`) tatsächlich kodieren.
 */

export interface SourceInfo {
  label: string;
  url?: string;
}

const STATIC_LABELS: Record<string, SourceInfo> = {
  fred: { label: "FRED (Federal Reserve)", url: "https://fred.stlouisfed.org" },
  eurostat: { label: "Eurostat", url: "https://ec.europa.eu/eurostat" },
  ecb: { label: "European Central Bank", url: "https://data.ecb.europa.eu" },
  ons: { label: "Office for National Statistics (UK)", url: "https://www.ons.gov.uk" },
  worldbank: { label: "World Bank", url: "https://data.worldbank.org" },
  destatis: { label: "Statistisches Bundesamt", url: "https://www-genesis.destatis.de" },
  bundesbank: { label: "Deutsche Bundesbank", url: "https://api.statistiken.bundesbank.de" },
  insee: { label: "INSEE", url: "https://www.insee.fr" },
  bdf: { label: "Banque de France", url: "https://www.banque-france.fr" },
  ine_es: { label: "INE Spain", url: "https://www.ine.es" },
  istat:  { label: "ISTAT (Italy)", url: "https://www.istat.it/en/" },
  cso_ie: { label: "CSO Ireland", url: "https://www.cso.ie/" },
  inept:  { label: "INE Portugal", url: "https://www.ine.pt/" },
  ine_pt: { label: "INE Portugal", url: "https://www.ine.pt/" },
  nbb:    { label: "National Bank of Belgium", url: "https://stat.nbb.be/" },
  elstat: { label: "ELSTAT (Greece)", url: "https://www.statistics.gr/en/home/" },
  scb:    { label: "Statistics Sweden (SCB)", url: "https://www.scb.se/" },
  scb_se: { label: "Statistics Sweden (SCB)", url: "https://www.scb.se/" },
  statpol:{ label: "Statistics Poland (GUS)", url: "https://stat.gov.pl/en/" },
  dst:    { label: "Statistics Denmark", url: "https://www.dst.dk/en" },
  stat_fi:{ label: "Statistics Finland", url: "https://www.stat.fi/index_en.html" },
  stat_at:{ label: "Statistik Austria", url: "https://www.statistik.at/" },
  surs_si:{ label: "SURS (Statistical Office Slovenia)", url: "https://www.stat.si/StatWeb/en" },
  csp_lv: { label: "Statistics Latvia (CSP)", url: "https://stat.gov.lv/en" },
  insse_ro:{ label: "INSSE Romania", url: "https://insse.ro/cms/en" },
  stat_ee: { label: "Statistics Estonia", url: "https://andmed.stat.ee" },
  dzs_hr:  { label: "DZS Croatian Bureau of Statistics", url: "https://web.dzs.hr" },
  statbel: { label: "Statbel (Belgium)", url: "https://statbel.fgov.be/en" },
  susr_sk: { label: "Štatistický úrad SR (Slovakia)", url: "https://slovak.statistics.sk" },
  eia: { label: "U.S. Energy Information Administration", url: "https://www.eia.gov" },
  gacc: {
    label: "General Administration of Customs of China",
    url: "http://english.customs.gov.cn",
  },
  curated: { label: "Hand-curated (annual reference)", url: "" },
};

// AkShare ist Wrapper für Eastmoney/Sina-Endpoints; die Upstream-Quelle steckt im
// series_id. Hier lösen wir auf das echte Original-Institut auf.
function resolveAkshareLabel(seriesId: string): SourceInfo {
  const pbocFns = [
    "macro_china_lpr",
    "macro_china_money_supply",
    "macro_china_supply_of_money",
    "macro_china_foreign_exchange_gold",
    "macro_china_central_bank_balance",
    "macro_china_new_financial_credit",
    "macro_china_reserve_requirement_ratio",
    "macro_china_shrzgm",
    "macro_china_shibor_all",
  ];
  if (pbocFns.some((fn) => seriesId.includes(fn))) {
    return { label: "People's Bank of China", url: "http://www.pbc.gov.cn/en" };
  }
  if (seriesId.includes("macro_china_hgjck")) {
    return {
      label: "General Administration of Customs of China",
      url: "http://english.customs.gov.cn",
    };
  }
  if (seriesId.includes("macro_china_safe")) {
    return {
      label: "State Administration of Foreign Exchange",
      url: "https://www.safe.gov.cn/en",
    };
  }
  return {
    label: "National Bureau of Statistics of China",
    url: "http://www.stats.gov.cn/english/",
  };
}

export function resolveSourceInfo(source: string, seriesId: string = ""): SourceInfo {
  if (source === "akshare") return resolveAkshareLabel(seriesId);
  // FRED-mirrored BIS series: ID pattern Q[CC][HPC]AM770A
  if (source === "fred" && /^Q[A-Z]{2}[HPC]AM770A$/.test(seriesId)) {
    return {
      label: "Bank for International Settlements (BIS)",
      url: "https://data.bis.org",
    };
  }
  return STATIC_LABELS[source] || { label: source };
}

export function resolveSourceUrl(source: string, seriesId: string = ""): string {
  if (source === "fred" && seriesId) return `https://fred.stlouisfed.org/series/${seriesId}`;
  if (source === "eurostat" && seriesId) {
    const dataset = seriesId.split(":")[0];
    return `https://ec.europa.eu/eurostat/databrowser/view/${dataset}`;
  }
  if (source === "worldbank" && seriesId)
    return `https://data.worldbank.org/indicator/${seriesId}`;
  if (source === "insee" && seriesId) {
    // series_id format: <DATASET>:<IDBANK>
    const idbank = seriesId.split(":")[1];
    if (idbank) return `https://www.insee.fr/fr/statistiques/serie/${idbank}`;
  }

  return resolveSourceInfo(source, seriesId).url || "";
}
