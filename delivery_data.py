from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean

import requests


SECTOR_SUB_MAP: dict[str, dict[str, list[str]]] = {
    "Banks & Financials": {
        "Private Banks": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK", "BANDHANBNK", "AUBANK", "FEDERALBNK"],
        "PSU Banks": ["SBIN", "PNB", "BANKBARODA", "CANARABANK", "UNIONBANK", "IOBBANK", "MAHABANK"],
        "NBFCs": ["BAJFINANCE", "BAJAJFINSV", "MUTHOOTFIN", "CHOLAFIN", "SHRIRAMFIN", "M&MFIN"],
        "Insurance": ["HDFCLIFE", "SBILIFE", "ICICIPRULI", "LICI", "GICRE"],
    },
    "Information Technology": {
        "Large Cap": ["TCS", "INFY", "HCLTECH", "WIPRO"],
        "Mid Cap": ["TECHM", "LTIM", "MPHASIS", "PERSISTENT", "COFORGE", "LTTS"],
        "Small Cap": ["KPITTECH", "TATAELXSI", "CYIENT", "MASTEK"],
    },
    "Auto": {
        "4-Wheeler": ["MARUTI", "M&M", "TATAMOTORS", "ESCORTS", "FORCEMOT"],
        "2-Wheeler": ["BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "TVSMOTOR"],
        "Ancillary": ["MOTHERSON", "BOSCHLTD", "MINDAIND", "EXIDEIND", "AMARAJABAT", "SUNDRMFAST"],
    },
    "Pharma & Healthcare": {
        "Large Pharma": ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "LUPIN", "ZYDUSLIFE"],
        "Mid Pharma": ["TORNTPHARM", "AUROPHARMA", "ALKEM", "GLENMARK", "IPCA", "ABBOTINDIA"],
        "Hospitals": ["APOLLOHOSP", "MAXHEALTH", "FORTIS", "KIMS", "RAINBOW"],
    },
    "FMCG & Consumption": {
        "Staples": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "GODREJCP"],
        "Personal Care": ["MARICO", "COLPAL", "EMAMILTD", "BAJAJCON"],
        "Beverages": ["TATACONSUM", "VARUNBEV", "MCDOWELL-N"],
    },
    "Energy & Utilities": {
        "Oil & Gas": ["RELIANCE", "ONGC", "BPCL", "IOC", "GAIL", "OIL", "MGL", "IGL"],
        "Power": ["NTPC", "POWERGRID", "TATAPOWER", "ADANIPOWER", "CESC", "TORNTPOWER"],
        "Renewables": ["ADANIGREEN", "NHPC", "SJVN", "INOXGREEN"],
    },
    "Metals & Materials": {
        "Steel": ["TATASTEEL", "JSWSTEEL", "SAIL", "JINDALSTEL", "NMDC", "MOIL"],
        "Non-Ferrous": ["HINDALCO", "VEDL", "NATIONALUM", "HINDCOPPER", "HINDZINC"],
        "Cement": ["ULTRACEMCO", "GRASIM", "SHREECEM", "ACC", "AMBUJACEM", "JKCEMENT"],
    },
    "Capital Goods & Infra": {
        "Capital Goods": ["LT", "SIEMENS", "ABB", "BEL", "BHEL", "THERMAX"],
        "Defence": ["HAL", "BEML", "MTAR", "PARAS", "COCHINSHIP"],
        "Infrastructure": ["IRCON", "RVNL", "ADANIPORTS", "CONCOR", "APLAPOLLO"],
    },
    "Realty": {
        "Developers": ["DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "BRIGADE", "LODHA", "MAHLIFE"],
        "Commercial": ["PHOENIXLTD", "NEXUSSELECT"],
    },
}

LARGECAP_SYMBOLS: frozenset[str] = frozenset({
    # Nifty 50
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BPCL", "BHARTIARTL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
    "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHREECEM",
    "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
    # Nifty Next 50
    "ABB", "ADANIGREEN", "ADANIPOWER", "AMBUJACEM", "ATGL",
    "BANKBARODA", "BHEL", "BOSCHLTD", "CANBK", "CGPOWER",
    "COLPAL", "DLF", "GAIL", "GODREJCP", "HAL",
    "HAVELLS", "HDFCAMC", "ICICIGI", "ICICIPRULI", "IOC",
    "IRFC", "LICI", "LODHA", "LTIM", "MARICO",
    "NAUKRI", "NHPC", "PFC", "PIDILITIND", "POLYCAB",
    "RECLTD", "SIEMENS", "TATAPOWER", "TIINDIA", "TORNTPOWER",
    "TVSMOTOR", "VEDL", "ZOMATO", "ZYDUSLIFE", "DMART",
    "JSWENERGY", "PERSISTENT", "GODREJPROP", "OBEROIRLTY",
    "MUTHOOTFIN", "SHRIRAMFIN", "CHOLAFIN", "PNB", "PAYTM",
})

MIDCAP_SYMBOLS: frozenset[str] = frozenset({
    "AARTIIND", "ABCAPITAL", "ACC", "ALKEM", "APOLLOTYRE",
    "APLAPOLLO", "ASHOKLEY", "ASTRAL", "AUBANK", "AUROPHARMA",
    "BANDHANBNK", "BEL", "BERGEPAINT", "BIOCON", "BRIGADE",
    "CONCOR", "COROMANDEL", "CROMPTON", "CUMMINSIND", "DELHIVERY",
    "ESCORTS", "EXIDEIND", "FEDERALBNK", "GLENMARK", "GRANULES",
    "HFCL", "IDFCFIRSTB", "IEX", "INDHOTEL", "IRCTC",
    "JKCEMENT", "JUBLFOOD", "KANSAINER", "KPITTECH", "LTTS",
    "LUPIN", "M&MFIN", "MAZDOCK", "MAXHEALTH", "MFSL",
    "MPHASIS", "NMDC", "OIL", "PAGEIND", "PETRONET",
    "PHOENIXLTD", "PIIND", "PRESTIGE", "SAIL", "SUPREMEIND",
    "SYNGENE", "TATACOMM", "TATACHEM", "TORNTPHARM", "UBL",
    "UNIONBANK", "VOLTAS", "WHIRLPOOL", "COFORGE", "KPIL",
    "MGL", "IGL", "MOIL", "HINDCOPPER", "NATIONALUM",
    "HINDZINC", "BALKRISIND", "DEEPAKNTR", "SUMICHEM", "NAVINFLUOR",
    "CHAMBLFERT", "EMAMILTD", "JYOTHYLAB", "KALYANKJIL", "KIMS",
    "FORTIS", "ABBOTINDIA", "IPCA", "SUNTV", "DEEPAKFERT",
    "JINDALSTEL", "SJVN", "COCHINSHIP", "BEML", "THERMAX",
    "MOTHERSON", "MINDAIND", "AMARAJABAT", "SUNDRMFAST", "LINDEINDIA",
})


def _cap_category(symbol: str) -> str:
    if symbol in LARGECAP_SYMBOLS:
        return "Large Cap"
    if symbol in MIDCAP_SYMBOLS:
        return "Mid Cap"
    return "Small Cap"


_SYMBOL_TO_SECTOR: dict[str, str] = {}
_SYMBOL_TO_SUBSECTOR: dict[str, str] = {}
for _sector, _subsectors in SECTOR_SUB_MAP.items():
    for _subsector, _syms in _subsectors.items():
        for _sym in _syms:
            _SYMBOL_TO_SECTOR[_sym] = _sector
            _SYMBOL_TO_SUBSECTOR[_sym] = _subsector


SECTOR_SYMBOLS: dict[str, list[str]] = {
    "Banks & Financials": [
        "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK",
        "BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "PFC", "RECLTD",
    ],
    "Information Technology": [
        "TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "MPHASIS",
        "PERSISTENT", "COFORGE",
    ],
    "Auto": [
        "MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO", "EICHERMOT",
        "HEROMOTOCO", "TVSMOTOR", "ASHOKLEY",
    ],
    "Pharma & Healthcare": [
        "SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "APOLLOHOSP",
        "LUPIN", "TORNTPHARM", "AUROPHARMA",
    ],
    "FMCG & Consumption": [
        "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR",
        "GODREJCP", "MARICO", "TATACONSUM",
    ],
    "Energy & Utilities": [
        "RELIANCE", "ONGC", "BPCL", "IOC", "NTPC", "POWERGRID",
        "TATAPOWER", "ADANIGREEN", "COALINDIA",
    ],
    "Metals & Materials": [
        "TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL",
        "NATIONALUM", "ULTRACEMCO", "GRASIM", "SHREECEM",
    ],
    "Capital Goods & Infrastructure": [
        "LT", "SIEMENS", "ABB", "HAL", "BEL", "BHEL", "IRCON",
        "RVNL", "ADANIPORTS",
    ],
    "Realty": [
        "DLF", "GODREJPROP", "OBEROIRLTY", "PHOENIXLTD", "PRESTIGE",
        "BRIGADE", "LODHA",
    ],
}


@dataclass
class TodayDeliveryStock:
    symbol: str
    delivery_percent: float
    close_price: float
    traded_qty: int
    delivery_qty: int
    high_price: float = 0.0
    low_price: float = 0.0
    sector: str = ""
    sub_sector: str = ""
    cap_category: str = ""
    name: str = ""

    @property
    def technical_score(self) -> float:
        rng = self.high_price - self.low_price
        if rng <= 0:
            return 50.0
        return (self.close_price - self.low_price) / rng * 100

    @property
    def combined_score(self) -> float:
        return self.delivery_percent * 0.5 + self.technical_score * 0.5

    @property
    def fund_label(self) -> str:
        if self.delivery_percent >= 65:
            return "Strong"
        if self.delivery_percent >= 45:
            return "Moderate"
        return "Weak"

    @property
    def fund_color(self) -> str:
        if self.delivery_percent >= 65:
            return "#0f9d58"
        if self.delivery_percent >= 45:
            return "#f9ab00"
        return "#d93025"

    @property
    def tech_label(self) -> str:
        ts = self.technical_score
        if ts >= 60:
            return "Bullish"
        if ts >= 40:
            return "Neutral"
        return "Bearish"

    @property
    def tech_color(self) -> str:
        ts = self.technical_score
        if ts >= 60:
            return "#0f9d58"
        if ts >= 40:
            return "#f9ab00"
        return "#d93025"

    @property
    def tech_arrow(self) -> str:
        ts = self.technical_score
        if ts >= 60:
            return "↑"
        if ts >= 40:
            return "→"
        return "↓"


@dataclass
class TodayDeliverySnapshot:
    stocks: list[TodayDeliveryStock]
    trade_date: date | None
    errors: list[str]

    @property
    def has_data(self) -> bool:
        return bool(self.stocks and self.trade_date)


@dataclass
class StockDeliveryStat:
    symbol: str
    sector: str
    avg_delivery_percent: float
    max_delivery_percent: float
    total_traded_qty: int
    total_delivery_qty: int
    days_counted: int


@dataclass
class SectorDeliveryLeaders:
    sector: str
    leaders: list[StockDeliveryStat]


@dataclass
class DeliverySnapshot:
    days: list[date]
    sectors: list[SectorDeliveryLeaders]
    errors: list[str]

    @property
    def has_data(self) -> bool:
        return bool(self.days and self.sectors)


def _to_int(value: str) -> int:
    cleaned = (value or "").replace(",", "").strip()
    if not cleaned or cleaned == "-":
        return 0
    return int(float(cleaned))


def _to_float(value: str) -> float:
    cleaned = (value or "").replace(",", "").strip()
    if not cleaned or cleaned == "-":
        return 0.0
    return float(cleaned)


def _download_bhavcopy(session: requests.Session, day: date, timeout_seconds: int) -> list[dict[str, str]]:
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv"
    response = session.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    text = response.text.strip()
    if "SYMBOL" not in text[:200]:
        raise ValueError("NSE response did not look like a bhavcopy CSV")
    reader = csv.DictReader(io.StringIO(text))
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def _fetch_equity_names(session: requests.Session, timeout_seconds: int) -> dict[str, str]:
    url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    try:
        resp = session.get(url, timeout=timeout_seconds)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text.strip()))
        names: dict[str, str] = {}
        for row in reader:
            sym = (row.get("SYMBOL") or "").strip().upper()
            raw_name = (row.get("NAME OF COMPANY") or "").strip()
            if sym and raw_name:
                names[sym] = raw_name.title()
        return names
    except Exception:
        return {}


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; IndianStockNewsAgent/1.0)",
            "Accept": "text/csv,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.nseindia.com/",
        }
    )
    return session


def fetch_weekly_delivery_snapshot(
    sector_symbols: dict[str, list[str]] | None = None,
    trading_days: int = 5,
    lookback_calendar_days: int = 12,
    top_per_sector: int = 5,
    min_total_traded_qty: int = 50_000,
    timeout_seconds: int = 20,
) -> DeliverySnapshot:
    sector_symbols = sector_symbols or SECTOR_SYMBOLS
    symbol_to_sector = {
        symbol.upper(): sector
        for sector, symbols in sector_symbols.items()
        for symbol in symbols
    }
    wanted_symbols = set(symbol_to_sector)
    session = _make_session()
    rows_by_symbol: dict[str, list[tuple[float, int, int]]] = {}
    used_days: list[date] = []
    errors: list[str] = []

    for offset in range(1, lookback_calendar_days + 1):
        if len(used_days) >= trading_days:
            break
        day = datetime.now().date() - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        try:
            rows = _download_bhavcopy(session, day, timeout_seconds)
        except Exception as exc:
            errors.append(f"{day:%Y-%m-%d}: {exc}")
            continue

        matched = 0
        for row in rows:
            symbol = row.get("SYMBOL", "").upper()
            series = row.get(" SERIES", row.get("SERIES", "")).upper()
            if symbol not in wanted_symbols or series != "EQ":
                continue

            delivery_percent = _to_float(row.get(" DELIV_PER", row.get("DELIV_PER", "")))
            traded_qty = _to_int(row.get(" TTL_TRD_QNTY", row.get("TTL_TRD_QNTY", "")))
            delivery_qty = _to_int(row.get(" DELIV_QTY", row.get("DELIV_QTY", "")))
            if delivery_percent <= 0 or traded_qty <= 0:
                continue
            rows_by_symbol.setdefault(symbol, []).append((delivery_percent, traded_qty, delivery_qty))
            matched += 1

        if matched:
            used_days.append(day)

    stats_by_sector: dict[str, list[StockDeliveryStat]] = {}
    for symbol, rows in rows_by_symbol.items():
        total_traded_qty = sum(row[1] for row in rows)
        if total_traded_qty < min_total_traded_qty:
            continue
        stat = StockDeliveryStat(
            symbol=symbol,
            sector=symbol_to_sector[symbol],
            avg_delivery_percent=mean(row[0] for row in rows),
            max_delivery_percent=max(row[0] for row in rows),
            total_traded_qty=total_traded_qty,
            total_delivery_qty=sum(row[2] for row in rows),
            days_counted=len(rows),
        )
        stats_by_sector.setdefault(stat.sector, []).append(stat)

    sectors = [
        SectorDeliveryLeaders(
            sector=sector,
            leaders=sorted(stats, key=lambda s: (s.avg_delivery_percent, s.total_delivery_qty), reverse=True)[
                :top_per_sector
            ],
        )
        for sector, stats in sorted(stats_by_sector.items())
        if stats
    ]

    return DeliverySnapshot(days=sorted(used_days), sectors=sectors, errors=errors[-5:])


def fetch_today_delivery_top(
    top_n: int = 40,
    min_traded_qty: int = 10_000,
    timeout_seconds: int = 20,
) -> TodayDeliverySnapshot:
    """Fetch the most recent trading day's NSE delivery data for all EQ stocks, sorted by delivery % descending."""
    session = _make_session()
    equity_names = _fetch_equity_names(session, timeout_seconds)
    errors: list[str] = []

    for offset in range(0, 8):
        day = datetime.now().date() - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        try:
            rows = _download_bhavcopy(session, day, timeout_seconds)
        except Exception as exc:
            errors.append(f"{day:%Y-%m-%d}: {exc}")
            continue

        stocks: list[TodayDeliveryStock] = []
        for row in rows:
            series = row.get("SERIES", row.get(" SERIES", "")).strip().upper()
            if series != "EQ":
                continue
            symbol = row.get("SYMBOL", "").strip().upper()
            if not symbol:
                continue
            delivery_percent = _to_float(row.get("DELIV_PER", row.get(" DELIV_PER", "")))
            traded_qty = _to_int(row.get("TTL_TRD_QNTY", row.get(" TTL_TRD_QNTY", "")))
            delivery_qty = _to_int(row.get("DELIV_QTY", row.get(" DELIV_QTY", "")))
            close_price = _to_float(row.get("CLOSE_PRICE", row.get(" CLOSE_PRICE", "")))
            if delivery_percent <= 0 or traded_qty < min_traded_qty:
                continue
            high_price = _to_float(row.get("HIGH_PRICE", row.get(" HIGH_PRICE", "")))
            low_price = _to_float(row.get("LOW_PRICE", row.get(" LOW_PRICE", "")))
            stocks.append(TodayDeliveryStock(
                symbol=symbol,
                delivery_percent=delivery_percent,
                close_price=close_price,
                traded_qty=traded_qty,
                delivery_qty=delivery_qty,
                high_price=high_price,
                low_price=low_price,
                sector=_SYMBOL_TO_SECTOR.get(symbol, ""),
                sub_sector=_SYMBOL_TO_SUBSECTOR.get(symbol, ""),
                cap_category=_cap_category(symbol),
                name=equity_names.get(symbol, ""),
            ))

        if stocks:
            stocks.sort(key=lambda s: s.delivery_percent, reverse=True)
            return TodayDeliverySnapshot(stocks=stocks[:top_n], trade_date=day, errors=errors)

    return TodayDeliverySnapshot(stocks=[], trade_date=None, errors=errors[-5:])


def build_sector_top(
    stocks: list[TodayDeliveryStock],
    top_n: int = 20,
) -> list[TodayDeliveryStock]:
    """Return top_n stocks from known sectors, ranked by combined fundamental+technical score."""
    sector_stocks = [s for s in stocks if s.sector]
    sector_stocks.sort(key=lambda s: s.combined_score, reverse=True)
    return sector_stocks[:top_n]
