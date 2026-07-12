from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
PREFIX = "trained_hr_model_simplified_raw_features"


def latest_board() -> Path:
    boards = sorted(ROOT.glob(f"{PREFIX}_board_????-??-??.csv"))
    boards = [p for p in boards if "graded" not in p.name]
    if not boards:
        raise FileNotFoundError("No daily board CSV was produced.")
    return boards[-1]


def clean(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def main() -> None:
    board_path = latest_board()
    frame = pd.read_csv(board_path).sort_values("ranking")
    columns = [
        "ranking", "game_pk", "commence_time", "batter_name_hand", "batting_team",
        "fielding_team", "is_home_batter", "game_matchup", "pitcher_name_hand",
        "final_hr_probability", "calibrated_hr_probability", "bet_quality_score",
        "batter_power", "recent_form", "pitcher_vulnerability", "handedness_splits",
        "pitch_type_matchup", "matchup_history", "environment", "pa_opportunity",
        "batter_hr_rate_prior", "batter_recent_hr_rate_10", "batter_recent_hr_rate_20",
        "batter_barrel_rate_prior", "batter_hard_hit_rate_prior", "batter_avg_ev_prior",
        "batter_hr_rate_vs_hand_prior", "pitcher_hr_rate_allowed_prior",
        "pitcher_recent_hr_allowed_rate_10", "pitcher_barrel_rate_allowed_prior",
        "pitcher_hard_hit_rate_allowed_prior", "pitcher_k_rate_prior",
        "matchup_pa_prior", "matchup_hr_prior", "matchup_hr_rate_prior",
        "pitch_fit_score_prior", "platoon_advantage", "temp_f", "wind_speed_mph",
        "weather_blowing_out", "wind_out_to_pull_flag", "pull_wind_mph",
        "relative_humidity", "is_roofed_no_wind", "park_factor",
    ]
    records = [
        {key: clean(value) for key, value in row.items()}
        for row in frame[[c for c in columns if c in frame.columns]].to_dict("records")
    ]
    target_date = str(frame["target_date"].iloc[0]) if "target_date" in frame else board_path.stem[-10:]
    payload = {
        "targetDate": target_date,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "featuredCount": min(50, len(records)),
        "rows": records,
    }
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    (SITE / "data" / "board.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    frame.to_csv(SITE / "data" / "latest-board.csv", index=False)


if __name__ == "__main__":
    main()
