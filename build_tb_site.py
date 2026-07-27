from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site" / "tb"
PREFIX = "trained_tb_model"


def clean(value):
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def backtest_payload() -> dict:
    summary_path = ROOT / f"{PREFIX}_backtest_summary.csv"
    scored_path = ROOT / f"{PREFIX}_scored_test_rows.csv"
    if not summary_path.exists() or not scored_path.exists():
        return {"summary": [], "daily": []}
    summary = pd.read_csv(summary_path)
    scored = pd.read_csv(scored_path)
    scored["game_date"] = pd.to_datetime(scored["game_date"], errors="coerce")
    scored = scored.dropna(subset=["game_date"])
    daily_records = []
    for top_n in [10, 20, 50]:
        ranked = (
            scored.sort_values(["game_date", "pred_tb_probability"], ascending=[True, False])
            .groupby("game_date", as_index=False, group_keys=False).head(top_n)
        )
        ranked = ranked.copy()
        ranked["daily_rank"] = ranked.groupby("game_date").cumcount() + 1
        detail_by_date = {}
        for game_date, picks in ranked.groupby("game_date", sort=True):
            detail_by_date[pd.Timestamp(game_date)] = [
                {
                    "rank": int(row["daily_rank"]),
                    "player": str(row.get("batter_name", f"Player {int(row['batter'])}")),
                    "team": str(row.get("batting_team", "")),
                    "opponent": str(row.get("fielding_team", "")),
                    "probability": float(row["pred_tb_probability"]),
                    "total_bases": int(row.get("total_bases", 0)),
                    "won": bool(row["tb_over_1_5"]),
                }
                for _, row in picks.iterrows()
            ]
        daily = ranked.groupby("game_date", as_index=False).agg(
            players=("batter", "count"),
            wins=("tb_over_1_5", "sum"),
            avg_model_probability=("pred_tb_probability", "mean"),
        )
        daily["hit_rate"] = daily["wins"] / daily["players"]
        daily["cumulative_players"] = daily["players"].cumsum()
        daily["cumulative_wins"] = daily["wins"].cumsum()
        daily["cumulative_hit_rate"] = daily["cumulative_wins"] / daily["cumulative_players"]
        daily["top_n"] = top_n
        daily["picks"] = daily["game_date"].map(detail_by_date)
        daily["game_date"] = daily["game_date"].dt.strftime("%Y-%m-%d")
        daily_records.extend(daily.to_dict("records"))
    available_dates = sorted(
        scored["game_date"].dt.strftime("%Y-%m-%d").dropna().unique().tolist()
    )
    return {
        "summary": [{k: clean(v) for k, v in r.items()} for r in summary.to_dict("records")],
        "daily": [{k: clean(v) for k, v in r.items()} for r in daily_records],
        "dateRange": {
            "min": available_dates[0] if available_dates else None,
            "max": available_dates[-1] if available_dates else None,
            "dates": available_dates,
        },
    }


def main() -> None:
    boards = sorted(ROOT.glob(f"{PREFIX}_board_????-??-??.csv"))
    if not boards:
        raise FileNotFoundError("No total-bases board CSV was produced.")
    frame = pd.read_csv(boards[-1]).sort_values("ranking")
    columns = [
        "ranking", "target_date", "commence_time", "batter_name_hand", "batting_team",
        "fielding_team", "game_matchup", "pitcher_name_hand", "final_tb_probability",
        "tb_signal", "batter_tb_per_pa_prior", "batter_hit_rate_prior",
        "batter_xbh_rate_prior", "batter_recent_tb_per_pa_10",
        "batter_recent_hit_rate_10", "pitcher_tb_allowed_per_pa_prior",
        "pitcher_hit_rate_allowed_prior", "pitcher_xbh_rate_allowed_prior",
        "pitcher_recent_tb_allowed_per_pa_10", "batter_recent_pa_10",
        "batter_barrel_rate_prior", "batter_hard_hit_rate_prior", "batter_avg_ev_prior",
        "pitcher_k_rate_prior", "platoon_advantage", "pitch_fit_score_prior",
        "temp_f", "wind_speed_mph", "relative_humidity", "park_factor",
        "lineup_confirmed", "lineup_status",
    ]
    records = [
        {k: clean(v) for k, v in row.items()}
        for row in frame[[c for c in columns if c in frame.columns]].to_dict("records")
    ]
    target_date = str(frame["target_date"].iloc[0])
    payload = {
        "targetDate": target_date,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "market": "Over 1.5 total bases",
        "rows": records,
        "backtest": backtest_payload(),
        "oddsStatus": "Projection-only board. Total-bases sportsbook odds are not connected yet.",
    }
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    (SITE / "data" / "board.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    frame.to_csv(SITE / "data" / "latest-board.csv", index=False)


if __name__ == "__main__":
    main()
