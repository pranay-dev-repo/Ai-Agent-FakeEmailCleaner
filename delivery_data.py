from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean

import requests


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
