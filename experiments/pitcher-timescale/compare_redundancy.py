import json
import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hr_model as hm


OUT = Path(__file__).resolve().parent / "redundancy_output"
OUT.mkdir(exist_ok=True)

WINDOWS = [
    ("2026-04-10_to_2026-05-09", "2026-03-10", "2026-04-09", "2026-05-09"),
    ("2026-05-10_to_2026-06-08", "2026-04-09", "2026-05-09", "2026-06-08"),
    ("2026-06-09_to_2026-07-07", "2026-05-09", "2026-06-08", "2026-07-07"),
    ("2026-07-08_to_2026-08-05", "2026-06-07", "2026-07-07", "2026-08-05"),
]

FIVE = [
    "pitcher_recent_k_rate_5",
    "pitcher_recent_fb_rate_allowed_5",
    "pitcher_recent_gb_rate_allowed_5",
]
TEN = [
    "pitcher_recent_k_rate_10",
    "pitcher_recent_fb_rate_allowed_10",
    "pitcher_recent_gb_rate_allowed_10",
]
LONG_TERM = [
    "pitcher_k_rate_prior",
    "pitcher_fb_rate_allowed_prior",
    "pitcher_gb_rate_allowed_prior",
]
TREND_PAIRS = {
    "pitcher_k_rate_5_minus_10": (FIVE[0], TEN[0]),
    "pitcher_fb_rate_5_minus_10": (FIVE[1], TEN[1]),
    "pitcher_gb_rate_5_minus_10": (FIVE[2], TEN[2]),
}
TRENDS = list(TREND_PAIRS)


def without(features, removals):
    remove = set(removals)
    return [feature for feature in features if feature not in remove]


def split_window(frame, train_end, valid_end, test_end):
    dates = pd.to_datetime(frame["game_date"])
    return (
        frame[dates <= pd.Timestamp(train_end)].copy(),
        frame[(dates > pd.Timestamp(train_end)) & (dates <= pd.Timestamp(valid_end))].copy(),
        frame[(dates > pd.Timestamp(valid_end)) & (dates <= pd.Timestamp(test_end))].copy(),
    )


def evaluate(variant, features, train, valid, test, window):
    hm.ACTIVE_FEATURE_COLUMNS = list(features)
    model, calibrator = hm.fit_calibrated_hgb(train, valid)
    raw = hm.predict_raw(model, test)
    calibrated = calibrator.transform(raw)
    scored = test[["game_date", "game_pk", "batter", "home_run_game"]].copy()
    scored["pred_hr_prob"] = raw
    probability = {
        "window": window,
        "variant": variant,
        "feature_count": len(features),
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
        summary.update(window=window, variant=variant, feature_count=len(features))
        top_rows.append(summary)
    return probability, top_rows


def main():
    pa = hm.load_statcast_pa(hm.FULL_DATA_START_DATE, hm.FULL_DATA_END_DATE, use_cache=True, refresh_cache=False)
    frame = hm.build_model_dataset(pa)
    for target, (short, medium) in TREND_PAIRS.items():
        frame[target] = pd.to_numeric(frame[short], errors="coerce").fillna(0) - pd.to_numeric(frame[medium], errors="coerce").fillna(0)

    baseline = list(hm.FULL_FEATURE_COLUMNS)
    variants = {
        "production_baseline": baseline,
        "add_five_start_only": baseline + [feature for feature in FIVE if feature not in baseline],
        "add_trends_only": baseline + [feature for feature in TRENDS if feature not in baseline],
        "replace_ten_with_five": without(baseline, TEN) + FIVE,
        "compact_fast_only": without(baseline, TEN + LONG_TERM) + FIVE,
    }

    probability_rows = []
    top_rows = []
    for window, train_end, valid_end, test_end in WINDOWS:
        train, valid, test = split_window(frame, train_end, valid_end, test_end)
        for variant, features in variants.items():
            probability, tops = evaluate(variant, features, train, valid, test, window)
            probability_rows.append(probability)
            top_rows.extend(tops)

    probability_df = pd.DataFrame(probability_rows)
    top_df = pd.DataFrame(top_rows)
    aggregate = top_df.groupby(["variant", "top_n"], as_index=False).agg(
        players=("total_players", "sum"),
        homers=("total_homers", "sum"),
        windows_won=("overall_hit_rate", lambda values: 0),
    )
    aggregate["hit_rate"] = aggregate["homers"] / aggregate["players"]
    baseline_rates = top_df[top_df["variant"].eq("production_baseline")].set_index(["window", "top_n"])["overall_hit_rate"]
    win_rows = []
    for (variant, top_n), group in top_df.groupby(["variant", "top_n"]):
        differences = [row.overall_hit_rate - baseline_rates.loc[(row.window, top_n)] for row in group.itertuples()]
        win_rows.append({
            "variant": variant,
            "top_n": top_n,
            "windows_better": sum(value > 0 for value in differences),
            "windows_tied": sum(value == 0 for value in differences),
            "windows_worse": sum(value < 0 for value in differences),
        })
    aggregate = aggregate.drop(columns=["windows_won"]).merge(pd.DataFrame(win_rows), on=["variant", "top_n"])
    production = aggregate[aggregate["variant"].eq("production_baseline")][["top_n", "hit_rate", "homers"]].rename(columns={"hit_rate": "baseline_hit_rate", "homers": "baseline_homers"})
    aggregate = aggregate.merge(production, on="top_n")
    aggregate["hit_rate_difference"] = aggregate["hit_rate"] - aggregate["baseline_hit_rate"]
    aggregate["extra_homers"] = aggregate["homers"] - aggregate["baseline_homers"]

    probability_df.to_csv(OUT / "redundancy_probability_metrics.csv", index=False)
    top_df.to_csv(OUT / "redundancy_top_n_metrics.csv", index=False)
    aggregate.to_csv(OUT / "redundancy_aggregate.csv", index=False)
    payload = {
        "windows": WINDOWS,
        "variant_features": variants,
        "probability_metrics": probability_df.to_dict("records"),
        "top_n_metrics": top_df.to_dict("records"),
        "aggregate": aggregate.to_dict("records"),
    }
    (OUT / "redundancy_comparison.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print("\n=== REDUNDANCY AGGREGATE ===")
    print(aggregate.sort_values(["top_n", "hit_rate"], ascending=[True, False]).to_string(index=False))
    print("\n=== PROBABILITY METRICS ===")
    print(probability_df.to_string(index=False))


if __name__ == "__main__":
    main()
