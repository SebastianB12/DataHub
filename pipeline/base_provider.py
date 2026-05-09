from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class DataPoint:
    indicator: str  # 'gdp', 'inflation-cpi'
    country: str  # 'US', 'DE', 'EA', 'GB'
    date: date
    value: float
    source: str  # 'fred', 'eurostat', 'ecb', 'ons'
    unit: str = ""  # 'Billion USD', 'Index', '% YoY', '%'
    series_id: str = ""  # Original series ID, e.g. 'CPIAUCSL', 'BBDP1.M.DE.N.VPI...'
    adjustment: str = ""  # 'SA' (seasonally adjusted), 'NSA' (not), or '' (not applicable)


class BaseProvider(ABC):
    name: str  # 'fred', 'eurostat'
    display_name: str  # 'Federal Reserve Economic Data'

    @abstractmethod
    def fetch(self) -> list[DataPoint]:
        """Fetch new/updated data points from the source."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} ({self.name})>"
