from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

import pandas as pd
from vegasinsider_odds import add_value_odds


ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
PREFIX = "trained_hr_model_simplified_raw_features"
HISTORY = SITE / "data" / "history"
HISTORY_BASE_URL = "https://dchang0611.github.io/hr-betting-model"


def fetch_json(url: str, attempts: int = 3) -> dict:
    """Fetch JSON with short retries for temporary GitHub Pages outages."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(url, timeout=20) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Could not fetch {url} after {attempts} attempts: {last_error}")


def restore_history() -> None:
    """Carry prior deployed slate snapshots into the next Pages artifact."""
    base = os.getenv("HISTORY_BASE_URL", HISTORY_BASE_URL).rstrip("/")
    HISTORY.mkdir(parents=True, exist_ok=True)
    try:
        index = fetch_json(f"{base}/data/history/index.json")
        for slate_date in index.get("dates", []):
            if not str(slate_date).replace("-", "").isdigit():
                continue
            destination = HISTORY / f"{slate_date}.json"
            if destination.exists():
                continue
            try:
                with urlopen(f"{base}/data/history/{slate_date}.json", timeout=20) as response:
                    destination.write_bytes(response.read())
            except Exception as exc:
                print(f"Could not restore historical slate {slate_date}: {exc}")
    except Exception as exc:
        print(f"No prior history index restored: {exc}")

    try:
        live_board = fetch_json(f"{base}/data/board.json")
        live_date = str(live_board.get("targetDate", ""))
        if live_date.replace("-", "").isdigit():
            live_archive = {key: value for key, value in live_board.items() if key != "backtest"}
            (HISTORY / f"{live_date}.json").write_text(
                json.dumps(live_archive, indent=2), encoding="utf-8"
            )
    except Exception as exc:
        print(f"No live board snapshot restored: {exc}")

    minimum_dates = int(os.getenv("MIN_HISTORY_DATES", "0"))
    restored_dates = set(path.stem for path in HISTORY.glob("????-??-??.json"))
    if len(restored_dates) < minimum_dates:
        raise RuntimeError(
            "History safety check failed: "
            f"found {len(restored_dates)} archived dates, but at least {minimum_dates} are required. "
            "Stopping before deployment so the existing website history is not overwritten."
        )


def live_backtest_fallback() -> dict:
    try:
        with urlopen(f"{HISTORY_BASE_URL}/data/board.json", timeout=15) as response:
            return json.load(response).get("backtest", {"summary": [], "daily": [], "drivers": []})
    except Exception:
        return {"summary": [], "daily": [], "drivers": []}


def normalize_player_name(value) -> str:
    """Normalize names so archived display labels can be joined to results."""
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"\s*\([LRS]\)\s*$", "", text, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def build_backtest_payload() -> dict:
    """Grade exact archived boards; use scored model rows only for outcomes."""
    scored_path = ROOT / f"{PREFIX}_scored_test_rows.csv"
    history_paths = sorted(HISTORY.glob("????-??-??.json"))
    if not scored_path.exists() or not history_paths:
        return live_backtest_fallback()

    scored = pd.read_csv(scored_path)
    scored["game_date"] = pd.to_datetime(scored["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    scored = scored.dropna(subset=["game_date"]).copy()
    scored["outcome"] = pd.to_numeric(scored["home_run_game"], errors="coerce")
    scored = scored.dropna(subset=["outcome"])
    scored["outcome"] = (scored["outcome"] > 0).astype(int)
    completed_dates = set(scored["game_date"].unique())
    name_col = next(
        (column for column in ["batter_name", "batter_name_hand", "player_name"] if column in scored.columns),
        None,
    )
    scored["name_key"] = scored[name_col].map(normalize_player_name) if name_col else ""
    scored["batter_key"] = (
        pd.to_numeric(scored["batter"], errors="coerce").astype("Int64")
        if "batter" in scored
        else pd.Series(pd.NA, index=scored.index, dtype="Int64")
    )
    scored["game_pk_key"] = (
        pd.to_numeric(scored["game_pk"], errors="coerce").astype("Int64")
        if "game_pk" in scored
        else pd.Series(pd.NA, index=scored.index, dtype="Int64")
    )
    id_rows = scored.dropna(subset=["batter_key"])
    name_rows = scored[scored["name_key"] != ""]
    outcome_by_game_id = id_rows.dropna(subset=["game_pk_key"]).groupby(
        ["game_date", "game_pk_key", "batter_key"]
    )["outcome"].max().to_dict()
    outcome_by_game_name = name_rows.dropna(subset=["game_pk_key"]).groupby(
        ["game_date", "game_pk_key", "name_key"]
    )["outcome"].max().to_dict()
    outcome_by_id = id_rows.groupby(["game_date", "batter_key"])["outcome"].max().to_dict()
    outcome_by_name = name_rows.groupby(["game_date", "name_key"])["outcome"].max().to_dict()

    board_rows = []
    shadow_rows = []
    for path in history_paths:
        try:
            archive = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Could not read historical board {path.name}: {exc}")
            continue
        game_date = str(archive.get("targetDate") or path.stem)
        for row_key, destination in [("rows", board_rows), ("shadowRows", shadow_rows)]:
            for fallback_rank, row in enumerate(archive.get(row_key, []), start=1):
                record = dict(row)
                record["game_date"] = game_date
                ranking = pd.to_numeric(record.get("ranking"), errors="coerce")
                record["ranking"] = int(ranking) if pd.notna(ranking) else fallback_rank
                probability = pd.to_numeric(
                    record.get("final_hr_probability", record.get("calibrated_hr_probability")), errors="coerce"
                )
                record["probability"] = probability / 100 if pd.notna(probability) and probability > 1 else probability
                batter_id = pd.to_numeric(record.get("batter"), errors="coerce")
                game_pk = pd.to_numeric(record.get("game_pk"), errors="coerce")
                display_name = record.get("batter_name_hand", record.get("batter_name", ""))
                name_key = normalize_player_name(display_name)
                outcome = None
                if pd.notna(game_pk) and pd.notna(batter_id):
                    outcome = outcome_by_game_id.get((game_date, int(game_pk), int(batter_id)))
                if outcome is None and pd.notna(game_pk):
                    outcome = outcome_by_game_name.get((game_date, int(game_pk), name_key))
                if outcome is None and pd.notna(batter_id):
                    outcome = outcome_by_id.get((game_date, int(batter_id)))
                if outcome is None:
                    outcome = outcome_by_name.get((game_date, name_key))
                if outcome is None and game_date in completed_dates:
                    outcome = 0
                record["outcome"] = outcome
                record["display_name"] = re.sub(
                    r"\s*\([LRS]\)\s*$", "", str(display_name), flags=re.IGNORECASE
                )
                destination.append(record)

    if not board_rows:
        return live_backtest_fallback()

    board = pd.DataFrame(board_rows).sort_values(["game_date", "ranking"])
    summary_records = []
    daily_records = []
    driver_records = []
    driver_columns = {
        "batter_power": "Batter power",
        "batter_recent_hr_rate_10": "Recent HR rate",
        "batter_barrel_rate_prior": "Barrel rate",
        "batter_hard_hit_rate_prior": "Hard-hit rate",
        "pitcher_vulnerability": "Pitcher vulnerability",
        "pitcher_hr_rate_allowed_prior": "Pitcher HR rate allowed",
        "pitcher_recent_hr_allowed_rate_10": "Recent pitcher HR rate allowed",
        "pitcher_k_rate_prior": "Pitcher strikeout rate",
        "park_factor": "Park factor",
        "temp_f": "Temperature",
        "pull_wind_mph": "Pull-side wind",
        "batter_recent_pa_10": "Recent plate appearances",
    }
    for top_n in [10, 20, 30, 40]:
        selected = board.groupby("game_date", as_index=False, group_keys=False).head(top_n).copy()
        ranked = selected[selected["outcome"].notna()].copy()
        if ranked.empty:
            continue
        ranked["outcome"] = pd.to_numeric(ranked["outcome"], errors="coerce")
        homer_hitters = {
            game_date: [
                {
                    "name": clean(row.display_name),
                    "rank": int(row.ranking),
                    "probability": clean(row.probability),
                }
                for row in group.sort_values("ranking").itertuples()
            ]
            for game_date, group in ranked[ranked["outcome"] > 0].groupby("game_date")
        }
        daily = ranked.groupby("game_date", as_index=False).agg(
            players=("outcome", "count"),
            homers=("outcome", "sum"),
            avg_model_prob=("probability", "mean"),
        ).sort_values("game_date")
        daily["hit_rate"] = daily["homers"] / daily["players"].replace(0, pd.NA)
        daily["cumulative_players"] = daily["players"].cumsum()
        daily["cumulative_homers"] = daily["homers"].cumsum()
        daily["cumulative_hit_rate"] = daily["cumulative_homers"] / daily["cumulative_players"]
        daily["top_n"] = top_n
        for row in daily.to_dict("records"):
            record = {key: clean(value) for key, value in row.items()}
            record["home_run_hitters"] = homer_hitters.get(record["game_date"], [])
            daily_records.append(record)
        summary_records.append({
            "top_n": top_n,
            "days": int(len(daily)),
            "total_players": int(daily["players"].sum()),
            "total_homers": int(daily["homers"].sum()),
            "avg_daily_hit_rate": clean(daily["hit_rate"].mean()),
            "overall_hit_rate": clean(daily["homers"].sum() / daily["players"].sum()),
            "avg_model_prob": clean(ranked["probability"].mean()),
        })
        available = [column for column in driver_columns if column in ranked.columns]
        if available and len(daily) >= 8:
            ranked[available] = ranked[available].apply(pd.to_numeric, errors="coerce")
            analysis = ranked.groupby("game_date")[available].mean(numeric_only=True).join(
                daily.set_index("game_date")["hit_rate"], how="inner"
            ).dropna(subset=["hit_rate"])
            low_cut = analysis["hit_rate"].quantile(0.25)
            high_cut = analysis["hit_rate"].quantile(0.75)
            for column in available:
                sample = analysis[[column, "hit_rate"]].dropna()
                if len(sample) < 8 or sample[column].nunique() < 2:
                    continue
                median = sample[column].median()
                lower = sample[sample[column] <= median]["hit_rate"]
                upper = sample[sample[column] > median]["hit_rate"]
                driver_records.append({
                    "top_n": top_n,
                    "metric": column,
                    "label": driver_columns[column],
                    "correlation": clean(sample[column].corr(sample["hit_rate"])),
                    "low_day_avg": clean(sample.loc[sample["hit_rate"] <= low_cut, column].mean()),
                    "high_day_avg": clean(sample.loc[sample["hit_rate"] >= high_cut, column].mean()),
                    "median": clean(median),
                    "hit_rate_below_median": clean(lower.mean()),
                    "hit_rate_above_median": clean(upper.mean()),
                    "days_below": int(len(lower)),
                    "days_above": int(len(upper)),
                })

    comparison_summary = []
    comparison_daily = []
    if shadow_rows:
        shadow = pd.DataFrame(shadow_rows).sort_values(["game_date", "ranking"])
        eligible_dates = sorted(set(board["game_date"]) & set(shadow["game_date"]))
        for top_n in [10, 20, 30, 40]:
            live_totals = shadow_totals = live_players = shadow_players = overlap_total = 0
            completed_days = 0
            for game_date in eligible_dates:
                live_day = board[board["game_date"].eq(game_date)].head(top_n)
                shadow_day = shadow[shadow["game_date"].eq(game_date)].head(top_n)
                live_day = live_day[live_day["outcome"].notna()].copy()
                shadow_day = shadow_day[shadow_day["outcome"].notna()].copy()
                if live_day.empty or shadow_day.empty:
                    continue
                live_homers = int(pd.to_numeric(live_day["outcome"], errors="coerce").fillna(0).sum())
                shadow_homers = int(pd.to_numeric(shadow_day["outcome"], errors="coerce").fillna(0).sum())
                if "batter" in live_day and "batter" in shadow_day:
                    live_ids = set(pd.to_numeric(live_day["batter"], errors="coerce").dropna().astype(int))
                    shadow_ids = set(pd.to_numeric(shadow_day["batter"], errors="coerce").dropna().astype(int))
                else:
                    live_ids = set(live_day["display_name"].map(normalize_player_name))
                    shadow_ids = set(shadow_day["display_name"].map(normalize_player_name))
                overlap = len(live_ids & shadow_ids)
                completed_days += 1
                live_players += len(live_day)
                shadow_players += len(shadow_day)
                live_totals += live_homers
                shadow_totals += shadow_homers
                overlap_total += overlap
                comparison_daily.append({
                    "game_date": game_date,
                    "top_n": top_n,
                    "live_players": len(live_day),
                    "shadow_players": len(shadow_day),
                    "live_homers": live_homers,
                    "shadow_homers": shadow_homers,
                    "homer_difference": live_homers - shadow_homers,
                    "overlap": overlap,
                    "overlap_rate": clean(overlap / max(1, min(len(live_day), len(shadow_day)))),
                })
            if completed_days:
                comparison_summary.append({
                    "top_n": top_n,
                    "days": completed_days,
                    "live_players": live_players,
                    "shadow_players": shadow_players,
                    "live_homers": live_totals,
                    "shadow_homers": shadow_totals,
                    "live_hit_rate": clean(live_totals / live_players),
                    "shadow_hit_rate": clean(shadow_totals / shadow_players),
                    "homer_difference": live_totals - shadow_totals,
                    "overlap_rate": clean(overlap_total / max(1, completed_days * top_n)),
                })

    comparison = {
        "startDate": min((row["game_date"] for row in comparison_daily), default=None),
        "completedDays": max((row["days"] for row in comparison_summary), default=0),
        "minimumDays": 30,
        "summary": comparison_summary,
        "daily": comparison_daily,
    }
    return {"summary": summary_records, "daily": daily_records, "drivers": driver_records, "comparison": comparison}


def latest_board() -> Path:
    boards = sorted(ROOT.glob(f"{PREFIX}_board_????-??-??.csv"))
    boards = [p for p in boards if "graded" not in p.name]
    if not boards:
        raise FileNotFoundError("No daily board CSV was produced.")
    return boards[-1]


def latest_shadow_board(target_date: str) -> Path | None:
    path = ROOT / f"{PREFIX}_shadow_board_{target_date}.csv"
    return path if path.exists() else None


def clean(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def main() -> None:
    restore_history()
    board_path = latest_board()
    frame = pd.read_csv(board_path).sort_values("ranking")
    target_date = str(frame["target_date"].iloc[0]) if "target_date" in frame else board_path.stem[-10:]
    frame, odds_status = add_value_odds(frame, target_date)
    source_date = odds_status.get("sourceDate")
    if source_date and source_date != target_date:
        historical_path = HISTORY / f"{source_date}.json"
        if historical_path.exists():
            historical_payload = json.loads(historical_path.read_text(encoding="utf-8"))
            historical_frame = pd.DataFrame(historical_payload.get("rows", []))
            if not historical_frame.empty:
                historical_frame, historical_status = add_value_odds(historical_frame, source_date)
                historical_payload["rows"] = [
                    {key: clean(value) for key, value in row.items()}
                    for row in historical_frame.to_dict("records")
                ]
                historical_payload["oddsStatus"] = historical_status
                historical_path.write_text(
                    json.dumps(historical_payload, indent=2), encoding="utf-8"
                )
                if historical_status.get("available"):
                    odds_status["message"] += (
                        f" Odds were attached to the archived {source_date} slate."
                    )
    columns = [
        "ranking", "batter", "game_pk", "commence_time", "batter_name_hand", "batting_team",
        "fielding_team", "is_home_batter", "game_matchup", "pitcher_name_hand",
        "starter_season_era", "starter_season_hr_allowed", "starter_season_ip",
        "final_hr_probability", "calibrated_hr_probability", "bet_quality_score",
        "batter_power", "recent_form", "pitcher_vulnerability", "handedness_splits",
        "pitch_type_matchup", "matchup_history", "environment", "pa_opportunity",
        "batter_pa_prior", "batter_recent_pa_10", "batter_hr_rate_prior",
        "batter_recent_hr_rate_10", "batter_recent_hr_rate_20",
        "batter_barrel_rate_prior", "batter_hard_hit_rate_prior", "batter_avg_ev_prior",
        "batter_hr_rate_vs_hand_prior", "pitcher_hr_rate_allowed_prior",
        "pitcher_recent_hr_allowed_rate_10", "pitcher_barrel_rate_allowed_prior",
        "pitcher_hard_hit_rate_allowed_prior", "pitcher_k_rate_prior",
        "matchup_pa_prior", "matchup_hr_prior", "matchup_hr_rate_prior",
        "pitch_fit_score_prior", "platoon_advantage", "temp_f", "wind_speed_mph",
        "weather_blowing_out", "wind_out_to_pull_flag", "pull_wind_mph",
        "wind_to_lf_mph", "wind_to_cf_mph", "wind_to_rf_mph",
        "relative_humidity", "is_roofed_no_wind", "park_factor",
        "best_hr_odds", "best_hr_book", "fanduel_hr_odds", "all_hr_odds",
        "market_implied_probability", "value_edge_pct_points",
        "expected_value_pct", "value_label",
    ]
    records = [
        {key: clean(value) for key, value in row.items()}
        for row in frame[[c for c in columns if c in frame.columns]].to_dict("records")
    ]
    shadow_records = []
    shadow_path = latest_shadow_board(target_date)
    if shadow_path:
        shadow_frame = pd.read_csv(shadow_path).sort_values("ranking")
        shadow_records = [
            {key: clean(value) for key, value in row.items()}
            for row in shadow_frame[[c for c in columns if c in shadow_frame.columns]].to_dict("records")
        ]
    archive_payload = {
        "targetDate": target_date,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "featuredCount": min(40, len(records)),
        "oddsStatus": odds_status,
        "rows": records,
        "shadowRows": shadow_records,
    }
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    (HISTORY / f"{target_date}.json").write_text(
        json.dumps(archive_payload, indent=2), encoding="utf-8"
    )
    payload = dict(archive_payload)
    payload["backtest"] = build_backtest_payload()
    (SITE / "data" / "board.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    history_dates = sorted((path.stem for path in HISTORY.glob("????-??-??.json")), reverse=True)
    (HISTORY / "index.json").write_text(
        json.dumps({"dates": history_dates}, indent=2), encoding="utf-8"
    )
    frame.to_csv(SITE / "data" / "latest-board.csv", index=False)


if __name__ == "__main__":
    main()
