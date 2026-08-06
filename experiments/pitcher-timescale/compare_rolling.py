import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hr_model as hm


OUT = Path(__file__).resolve().parent / "rolling_output"
OUT.mkdir(exist_ok=True)

WINDOWS = [
    ("2026-04-10_to_2026-05-09", "2026-03-10", "2026-04-09", "2026-05-09"),
    ("2026-05-10_to_2026-06-08", "2026-04-09", "2026-05-09", "2026-06-08"),
    ("2026-06-09_to_2026-07-07", "2026-05-09", "2026-06-08", "2026-07-07"),
    ("2026-07-08_to_2026-08-05", "2026-06-07", "2026-07-07", "2026-08-05"),
]

FAST_PAIRS = {
    "pitcher_k_rate_5_minus_10": ("pitcher_recent_k_rate_5", "pitcher_recent_k_rate_10"),
    "pitcher_fb_rate_5_minus_10": ("pitcher_recent_fb_rate_allowed_5", "pitcher_recent_fb_rate_allowed_10"),
    "pitcher_gb_rate_5_minus_10": ("pitcher_recent_gb_rate_allowed_5", "pitcher_recent_gb_rate_allowed_10"),
}
EXTRAS = [
    "pitcher_recent_k_rate_5",
    "pitcher_recent_fb_rate_allowed_5",
    "pitcher_recent_gb_rate_allowed_5",
    *FAST_PAIRS.keys(),
]


def split_window(frame, train_end, valid_end, test_end):
    dates = pd.to_datetime(frame["game_date"])
    train = frame[dates <= pd.Timestamp(train_end)].copy()
    valid = frame[(dates > pd.Timestamp(train_end)) & (dates <= pd.Timestamp(valid_end))].copy()
    test = frame[(dates > pd.Timestamp(valid_end)) & (dates <= pd.Timestamp(test_end))].copy()
    return train, valid, test


def evaluate(name, features, train, valid, test, window):
    hm.ACTIVE_FEATURE_COLUMNS = list(features)
    model, calibrator = hm.fit_calibrated_hgb(train, valid)
    raw = hm.predict_raw(model, test)
    calibrated = calibrator.transform(raw)
    scored = test[["game_date", "game_pk", "batter", "home_run_game"]].copy()
    scored["pred_hr_prob"] = raw
    scored["calibrated_hr_prob"] = calibrated
    probability = {
        "window": window,
        "model": name,
        "train_rows": len(train),
        "validation_rows": len(valid),
        "test_rows": len(test),
        "test_days": int(scored["game_date"].nunique()),
        "raw_log_loss": float(log_loss(scored["home_run_game"], raw)),
        "raw_brier": float(brier_score_loss(scored["home_run_game"], raw)),
        "raw_auc": float(roc_auc_score(scored["home_run_game"], raw)),
        "calibrated_log_loss": float(log_loss(scored["home_run_game"], calibrated)),
        "calibrated_brier": float(brier_score_loss(scored["home_run_game"], calibrated)),
    }
    top_rows = []
    for top_n in [10, 20, 30, 40]:
        summary = hm.summarize_top_n(scored, top_n)
        summary.update(window=window, model=name)
        top_rows.append(summary)
    scored.to_csv(OUT / f"{window}_{name}_scored.csv", index=False)
    return probability, top_rows


def main():
    pa = hm.load_statcast_pa(hm.FULL_DATA_START_DATE, hm.FULL_DATA_END_DATE, use_cache=True, refresh_cache=False)
    frame = hm.build_model_dataset(pa)
    for target, (short, medium) in FAST_PAIRS.items():
        frame[target] = pd.to_numeric(frame[short], errors="coerce").fillna(0) - pd.to_numeric(frame[medium], errors="coerce").fillna(0)

    baseline = list(hm.FULL_FEATURE_COLUMNS)
    challenger = baseline + [feature for feature in EXTRAS if feature not in baseline]
    probability_rows = []
    top_rows = []
    for window, train_end, valid_end, test_end in WINDOWS:
        train, valid, test = split_window(frame, train_end, valid_end, test_end)
        for name, features in [("production_baseline", baseline), ("fast_pitcher_challenger", challenger)]:
            probability, tops = evaluate(name, features, train, valid, test, window)
            probability_rows.append(probability)
            top_rows.extend(tops)

    probability_df = pd.DataFrame(probability_rows)
    top_df = pd.DataFrame(top_rows)
    probability_df.to_csv(OUT / "rolling_probability_metrics.csv", index=False)
    top_df.to_csv(OUT / "rolling_top_n_metrics.csv", index=False)
    comparison = top_df.pivot(index=["window", "top_n"], columns="model", values=["total_homers", "overall_hit_rate"]).reset_index()
    comparison.columns = ["_".join(str(part) for part in column if part).strip("_") if isinstance(column, tuple) else column for column in comparison.columns]
    comparison["extra_homers"] = comparison["total_homers_fast_pitcher_challenger"] - comparison["total_homers_production_baseline"]
    comparison["hit_rate_difference"] = comparison["overall_hit_rate_fast_pitcher_challenger"] - comparison["overall_hit_rate_production_baseline"]
    comparison.to_csv(OUT / "rolling_direct_comparison.csv", index=False)
    payload = {
        "windows": WINDOWS,
        "challenger_features": EXTRAS,
        "probability_metrics": probability_df.to_dict("records"),
        "top_n_metrics": top_df.to_dict("records"),
        "direct_comparison": comparison.to_dict("records"),
    }
    (OUT / "rolling_comparison.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print("\n=== ROLLING DIRECT COMPARISON ===")
    print(comparison.to_string(index=False))
    print("\n=== ROLLING PROBABILITY METRICS ===")
    print(probability_df.to_string(index=False))


if __name__ == "__main__":
    main()
