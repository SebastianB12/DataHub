export const INDICATOR_CATEGORIES = [
  {
    slug: "gdp-growth",
    name: "GDP & Growth",
    name_de: "BIP & Wachstum",
    indicators: ["gdp", "gdp-real", "gdp-growth", "gdp-per-capita"],
  },
  {
    slug: "inflation-prices",
    name: "Inflation & Prices",
    name_de: "Inflation & Preise",
    indicators: ["inflation-cpi", "core-cpi", "ppi"],
  },
  {
    slug: "labor",
    name: "Labor Market",
    name_de: "Arbeitsmarkt",
    indicators: ["unemployment", "employment-rate", "population"],
  },
  {
    slug: "monetary",
    name: "Interest Rates & Monetary Policy",
    name_de: "Zinsen & Geldpolitik",
    indicators: ["interest-rate", "central-bank-balance", "money-supply-m2"],
  },
  {
    slug: "trade",
    name: "Trade & External",
    name_de: "Handel & Aussenwirtschaft",
    indicators: ["trade-balance", "current-account", "exports", "imports"],
  },
  {
    slug: "government",
    name: "Government Finance",
    name_de: "Staatsfinanzen",
    indicators: ["government-debt", "budget-deficit"],
  },
] as const;

export const COUNTRIES = [
  { code: "US", name: "United States", name_de: "USA", flag: "\u{1F1FA}\u{1F1F8}" },
  { code: "EA", name: "Euro Area", name_de: "Euro-Raum", flag: "\u{1F1EA}\u{1F1FA}" },
  { code: "GB", name: "United Kingdom", name_de: "UK", flag: "\u{1F1EC}\u{1F1E7}" },
  { code: "DE", name: "Germany", name_de: "Deutschland", flag: "\u{1F1E9}\u{1F1EA}" },
] as const;
