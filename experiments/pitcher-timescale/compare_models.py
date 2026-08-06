import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hr_model as hm


OUT = Path(__file__).resolve().parent / "comparison_output"
OUT.mkdir(exist_ok=True)


def expected_calibration_error(y_true, probability, bins=10):
    frame = pd.DataFrame({"y": np.asarray(y_true), "p": np.asarray(probability)})
    frame["bin"] = pd.cut(frame["p"], bins=np.linspace(0, 1, bins + 1), include_lowest=True)
    grouped = frame.groupby("bin", observed=False).agg(count=("y", "size"), actual=("y", "mean"), predicted=("p", "mean")).dropna()
    return float(((grouped["count"] / len(frame)) * (grouped["actual"] - grouped["predicted"]).abs()).sum())


def score_model(name, features, train_df, valid_df, test_df):
    hm.ACTIVE_FEATURE_COLUMNS = list(features)
    model, calibrator = hm.fit_calibrated_hgb(train_df, valid_df)
    raw = hm.predict_raw(model, test_df)
    calibrated = calibrator.transform(raw)
    scored = test_df[["game_date", "game_pk", "batter", "home_run_game"]].copy()
    scored["pred_hr_prob"] = raw
    scored["calibrated_hr_prob"] = calibrated
    metrics = {
        "model": name,
        "features": len(features),
        "test_rows": len(scored),
        "test_days": int(scored["game_date"].nunique()),
        "raw_log_loss": float(log_loss(scored["home_run_game"], raw)),
        "raw_brier": float(brier_score_loss(scored["home_run_game"], raw)),
        "raw_auc": float(roc_auc_score(scored["home_run_game"], raw)),
        "calibrated_log_loss": float(log_loss(scored["home_run_game"], calibrated)),
        "calibrated_brier": float(brier_score_loss(scored["home_run_game"], calibrated)),
        "calibration_error": expected_calibration_error(scored["home_run_game"], calibrated),
    }
    top_rows = []
    for top_n in [10, 20, 30, 40]:
        summary = hm.summarize_top_n(scored, top_n)
        summary["model"] = name
        top_rows.append(summary)
    scored.to_csv(OUT / f"{name}_scored.csv", index=False)
    return metrics, top_rows


def main():
    pa_df = hm.load_statcast_pa(hm.FULL_DATA_START_DATE, hm.FULL_DATA_END_DATE, use_cache=True, refresh_cache=False)
    model_df = hm.build_model_dataset(pa_df)

    fast_pairs = {
        "pitcher_k_rate_5_minus_10": ("pitcher_recent_k_rate_5", "pitcher_recent_k_rate_10"),
        "pitcher_fb_rate_5_minus_10": ("pitcher_recent_fb_rate_allowed_5", "pitcher_recent_fb_rate_allowed_10"),
        "pitcher_gb_rate_5_minus_10": ("pitcher_recent_gb_rate_allowed_5", "pitcher_recent_gb_rate_allowed_10"),
    }
    for target, (short, medium) in fast_pairs.items():
        model_df[target] = pd.to_numeric(model_df[short], errors="coerce").fillna(0) - pd.to_numeric(model_df[medium], errors="coerce").fillna(0)

    train_df, valid_df, test_df = hm.split_model_dataset(model_df)
    baseline = list(hm.FULL_FEATURE_COLUMNS)
    challenger_extras = [
        "pitcher_recent_k_rate_5",
        "pitcher_recent_fb_rate_allowed_5",
        "pitcher_recent_gb_rate_allowed_5",
        *fast_pairs.keys(),
    ]
    challenger = baseline + [feature for feature in challenger_extras if feature not in baseline]

    all_metrics = []
    all_top = []
    for name, features in [("production_baseline", baseline), ("fast_pitcher_challenger", challenger)]:
        metrics, top_rows = score_model(name, features, train_df, valid_df, test_df)
        all_metrics.append(metrics)
        all_top.extend(top_rows)

    metrics_df = pd.DataFrame(all_metrics)
    top_df = pd.DataFrame(all_top)
    metrics_df.to_csv(OUT / "probability_metrics.csv", index=False)
    top_df.to_csv(OUT / "top_n_metrics.csv", index=False)
    payload = {
        "date_boundaries": {
            "data_start": hm.FULL_DATA_START_DATE,
            "data_end": hm.FULL_DATA_END_DATE,
            "train_end": hm.TRAIN_END_DATE,
            "validation_end": hm.VALID_END_DATE,
        },
        "challenger_features": challenger_extras,
        "probability_metrics": metrics_df.to_dict("records"),
        "top_n_metrics": top_df.to_dict("records"),
    }
    (OUT / "comparison.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print("\n=== PROBABILITY COMPARISON ===")
    print(metrics_df.to_string(index=False))
    print("\n=== TOP-N COMPARISON ===")
    print(top_df.to_string(index=False))


if __name__ == "__main__":
    main()
