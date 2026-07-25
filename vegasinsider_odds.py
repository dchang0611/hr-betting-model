from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone

import pandas as pd
import requests
from bs4 import BeautifulSoup


VEGASINSIDER_HR_URL = "https://www.vegasinsider.com/mlb/odds/player-props/home-runs/"
USER_AGENT = "Mozilla/5.0 (compatible; HRValueBoard/1.0; +https://github.com/)"


def normalize_player_name(value: object) -> str:
    text = re.sub(r"\s+\([LRS]\)\s*$", "", str(value or ""), flags=re.I)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def american_implied_probability(odds: int) -> float:
    return 100 / (odds + 100) if odds > 0 else abs(odds) / (abs(odds) + 100)


def parse_vegasinsider_html(html: str) -> tuple[str | None, list[dict]]:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1", string=re.compile(r"Home Run Odds", re.I))
    date_match = re.search(r"(\d{2})/(\d{2})/(\d{4})", heading.get_text(" ", strip=True) if heading else "")
    source_date = f"{date_match.group(3)}-{date_match.group(1)}-{date_match.group(2)}" if date_match else None
    table = soup.select_one("table#table-home-runs")
    if table is None:
        raise ValueError("VegasInsider home-run odds table was not found.")
    books = []
    for cell in table.select("thead tr:first-child th")[1:]:
        hidden = cell.select_one(".hidden")
        books.append(hidden.get_text(" ", strip=True) if hidden else "")
    records = []
    for row in table.select("tbody#see-all-home-runs tr[data-name]"):
        cells = row.find_all("td", recursive=False)
        if not cells:
            continue
        player = cells[0].get_text(" ", strip=True)
        prices = {}
        for index, cell in enumerate(cells[1:]):
            if index >= len(books) or not books[index]:
                continue
            matches = re.findall(r"(?<![\d.])([+-]\d{3,5})(?!\d)", cell.get_text(" ", strip=True))
            if matches:
                price = int(matches[-1])
                if -10000 < price < 10000 and price:
                    prices[books[index]] = price
        if prices:
            best_book, best_odds = max(
                prices.items(),
                key=lambda item: (1 + item[1] / 100) if item[1] > 0 else (1 + 100 / abs(item[1])),
            )
            records.append({
                "player_name": player,
                "player_key": normalize_player_name(player),
                "best_hr_odds": best_odds,
                "best_hr_book": best_book,
                "fanduel_hr_odds": prices.get("FanDuel"),
                "all_hr_odds": json.dumps(prices, sort_keys=True),
            })
    if not records:
        raise ValueError("VegasInsider table contained no usable American HR odds.")
    return source_date, records


def fetch_vegasinsider_odds(timeout: int = 30) -> tuple[str | None, list[dict], str]:
    response = requests.get(
        VEGASINSIDER_HR_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=timeout,
    )
    response.raise_for_status()
    source_date, records = parse_vegasinsider_html(response.text)
    return source_date, records, datetime.now(timezone.utc).isoformat()


def add_value_odds(frame: pd.DataFrame, target_date: str) -> tuple[pd.DataFrame, dict]:
    out = frame.copy()
    status = {
        "available": False, "source": "VegasInsider", "sourceUrl": VEGASINSIDER_HR_URL,
        "sourceDate": None, "scrapedAt": None, "matchedPlayers": 0,
        "message": "Live HR odds were not available.",
    }
    try:
        source_date, records, scraped_at = fetch_vegasinsider_odds()
        status.update(sourceDate=source_date, scrapedAt=scraped_at)
        if source_date != target_date:
            status["message"] = f"VegasInsider is showing {source_date or 'an unknown date'}, not the {target_date} model slate."
            return out, status
        odds = pd.DataFrame(records).drop_duplicates("player_key", keep="first")
        out["player_key"] = out["batter_name_hand"].map(normalize_player_name)
        out = out.merge(odds, on="player_key", how="left").drop(columns=["player_key"])
        model_prob = pd.to_numeric(out.get("calibrated_hr_probability"), errors="coerce") / 100
        prices = pd.to_numeric(out.get("best_hr_odds"), errors="coerce")
        out["market_implied_probability"] = prices.map(
            lambda value: american_implied_probability(int(value)) if pd.notna(value) else float("nan")
        )
        out["value_edge_pct_points"] = ((model_prob - out["market_implied_probability"]) * 100).round(1)
        decimal_price = prices.map(
            lambda value: (1 + value / 100) if pd.notna(value) and value > 0
            else ((1 + 100 / abs(value)) if pd.notna(value) and value < 0 else float("nan"))
        )
        out["expected_value_pct"] = ((model_prob * decimal_price - 1) * 100).round(1)

        def label(row: pd.Series) -> str:
            edge, ev = row.get("value_edge_pct_points"), row.get("expected_value_pct")
            if pd.isna(edge) or pd.isna(ev):
                return "No verified odds"
            if edge >= 5 and ev >= 20:
                return "Strong value"
            if edge >= 3 and ev >= 10:
                return "Value"
            if edge >= 1.5 and ev >= 5:
                return "Watch"
            return "Pass"

        out["value_label"] = out.apply(label, axis=1)
        matched = int(out["best_hr_odds"].notna().sum())
        status.update(available=matched > 0, matchedPlayers=matched, message=f"Matched current HR odds for {matched} model players.")
    except Exception as exc:
        status["message"] = f"Odds unavailable; model board published without value picks ({type(exc).__name__})."
    return out, status
