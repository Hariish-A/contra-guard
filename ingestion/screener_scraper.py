"""
ingestion/screener_scraper.py
-----------------------------
Pulls structured financial data from Screener.in for a given company.

What we scrape:
  - Quarterly results table (Revenue, EBITDA, Net Profit, EPS)
  - Key ratios (ROCE, ROE, Debt/Equity)
  - Company metadata (name, industry, description)

Screener.in has a clean HTML structure that doesn't require JS rendering.
We use requests + BeautifulSoup.

Usage:
    data = scrape_screener("INFY")   # NSE ticker or BSE code
    print(data["quarterly_results"])

Note: Screener.in does not require login for basic data pages.
      Rate-limit yourself: stay under ~10 req/min to be polite.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
from loguru import logger
import pandas as pd

# ──────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────
SCREENER_BASE = "https://www.screener.in/company/{ticker}/consolidated/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Quarter label regex: "Mar 2024", "Jun 2023" etc.
QUARTER_PATTERN = re.compile(r"(Mar|Jun|Sep|Dec)\s+(\d{4})")

# Map month → Indian FY quarter
MONTH_TO_Q = {"Jun": "Q1", "Sep": "Q2", "Dec": "Q3", "Mar": "Q4"}


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def scrape_screener(ticker: str) -> Dict:
    """
    Scrape Screener.in for *ticker* (NSE symbol preferred, e.g. 'INFY', 'RELIANCE').

    Returns:
    {
      "ticker":            str,
      "name":              str,
      "sector":            str,
      "quarterly_results": pd.DataFrame,   # rows=metrics, cols=quarters
      "key_ratios":        dict,
      "raw_html":          str             # for debugging
    }
    """
    url  = SCREENER_BASE.format(ticker=ticker.upper())
    logger.info(f"[Screener] Fetching {url}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.HTTPError as exc:
        if resp.status_code == 404:
            # Try standalone (non-consolidated) page
            url  = url.replace("/consolidated/", "/")
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        else:
            raise

    soup = BeautifulSoup(resp.text, "lxml")

    result = {
        "ticker":            ticker.upper(),
        "name":              _get_company_name(soup),
        "sector":            _get_sector(soup),
        "quarterly_results": _parse_quarterly_results(soup),
        "key_ratios":        _parse_key_ratios(soup),
        "raw_html":          resp.text,
    }

    logger.info(
        f"[Screener] {result['name']} | sector={result['sector']} | "
        f"quarters={len(result['quarterly_results'].columns) if isinstance(result['quarterly_results'], pd.DataFrame) else 0}"
    )
    return result


def get_quarterly_actuals(ticker: str) -> pd.DataFrame:
    """
    Convenience: returns just the quarterly financials DataFrame.
    Columns are quarter labels like 'Q1FY24'.
    Rows include: Sales, Expenses, Operating Profit, OPM%, Other Income,
                  Interest, Depreciation, Profit before tax, Tax%, Net Profit, EPS.
    """
    data = scrape_screener(ticker)
    return data["quarterly_results"]


# ──────────────────────────────────────────────────────────────────
# Parsing helpers
# ──────────────────────────────────────────────────────────────────

def _get_company_name(soup: BeautifulSoup) -> str:
    tag = soup.find("h1", class_=re.compile(r"company-name|h1", re.I))
    if tag:
        return tag.get_text(strip=True)
    title = soup.find("title")
    return title.get_text(strip=True).split("|")[0].strip() if title else ""


def _get_sector(soup: BeautifulSoup) -> str:
    # Screener shows "Sector: Banking" in a span inside .company-ratios or .breadcrumb
    for tag in soup.find_all("a"):
        href = tag.get("href", "")
        if "/stocks/" in href and "sector" in href.lower():
            return tag.get_text(strip=True)
    return ""


def _parse_quarterly_results(soup: BeautifulSoup) -> pd.DataFrame:
    """
    Find the Quarterly Results table on Screener and return it as a DataFrame.
    Column headers are normalised to 'Q1FY24' style labels.
    """
    section = soup.find("section", id="quarters")
    if not section:
        logger.warning("[Screener] Quarterly results section not found")
        return pd.DataFrame()

    table = section.find("table")
    if not table:
        return pd.DataFrame()

    # Header row = quarter labels
    header_row = table.find("thead")
    if not header_row:
        return pd.DataFrame()

    raw_headers = [th.get_text(strip=True) for th in header_row.find_all("th")]
    # raw_headers[0] is usually empty or "Metric"
    quarters = [_normalise_quarter(h) for h in raw_headers[1:]]

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 2:
            continue
        metric = cells[0]
        values = [_parse_number(c) for c in cells[1:len(quarters)+1]]
        rows.append([metric] + values)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["metric"] + quarters)
    df = df.set_index("metric")
    return df


def _parse_key_ratios(soup: BeautifulSoup) -> dict:
    """Parse the key ratios list from Screener (ROCE, ROE, PE, etc.)."""
    ratios = {}
    section = soup.find("section", id="ratios")
    if not section:
        return ratios

    for li in section.find_all("li"):
        name_tag  = li.find("span", class_="name")
        value_tag = li.find("span", class_="value")
        if name_tag and value_tag:
            key = name_tag.get_text(strip=True)
            val = value_tag.get_text(strip=True)
            ratios[key] = _parse_number(val)

    return ratios


def _normalise_quarter(label: str) -> str:
    """
    Convert 'Jun 2023' → 'Q1FY24',  'Mar 2024' → 'Q4FY24', etc.
    If the label doesn't match, return it as-is.
    """
    m = QUARTER_PATTERN.search(label)
    if not m:
        return label
    month = m.group(1)  # Jun, Sep, Dec, Mar
    year  = int(m.group(2))
    q_label = MONTH_TO_Q.get(month, "Q?")

    # Indian FY: Q4 (Mar) belongs to the FY ending that year
    # e.g. Mar 2024 → Q4FY24;  Jun 2023 → Q1FY24 (FY starts Apr 2023)
    if month == "Mar":
        fy = year
    else:
        fy = year + 1

    fy_short = str(fy)[2:]   # 2024 → "24"
    return f"{q_label}FY{fy_short}"


def _parse_number(s: str) -> Optional[float]:
    """Convert '1,234.56' or '12.5%' or '-' to float. Returns None on failure."""
    s = s.replace(",", "").replace("%", "").replace("₹", "").strip()
    if s in ("", "-", "N/A", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ──────────────────────────────────────────────────────────────────
# Batch scrape for multiple tickers
# ──────────────────────────────────────────────────────────────────

def batch_scrape(tickers: List[str], delay_sec: float = 2.0) -> Dict[str, Dict]:
    """
    Scrape multiple tickers with a polite delay between requests.
    Returns dict: { ticker → scrape_screener result }
    """
    results = {}
    for ticker in tickers:
        try:
            results[ticker] = scrape_screener(ticker)
        except Exception as exc:
            logger.error(f"[Screener] Failed for {ticker}: {exc}")
            results[ticker] = {}
        time.sleep(delay_sec)
    return results


# ──────────────────────────────────────────────────────────────────
# Quick test
# ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "INFY"
    data   = scrape_screener(ticker)
    print(f"\nCompany : {data['name']}")
    print(f"Sector  : {data['sector']}")
    print("\nQuarterly Results:")
    if isinstance(data["quarterly_results"], pd.DataFrame) and not data["quarterly_results"].empty:
        print(data["quarterly_results"].to_string())
    print("\nKey Ratios:", data["key_ratios"])
