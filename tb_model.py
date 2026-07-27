from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

import hr_model as base


PREFIX = "trained_tb_model"
TARGET_COLUMN = "tb_over_1_5"
TB_FEATURES = [
    "batter_tb_per_pa_prior",
    "batter_hit_rate_prior",
    "batter_xbh_rate_prior",
    "batter_recent_tb_per_pa_10",
    "batter_recent_hit_rate_10",
    "pitcher_tb_allowed_per_pa_prior",
    "pitcher_hit_rate_allowed_prior",
    "pitcher_xbh_rate_allowed_prior",
    "pitcher_recent_tb_allowed_per_pa_10",
]
PITCHER_TB_RENAMES = {
    "pitcher_tb_per_pa_prior": "pitcher_tb_allowed_per_pa_prior",
    "pitcher_hit_rate_prior": "pitcher_hit_rate_allowed_prior",
    "pitcher_xbh_rate_prior": "pitcher_xbh_rate_allowed_prior",
    "pitcher_recent_tb_per_pa_10": "pitcher_recent_tb_allowed_per_pa_10",
}


def add_event_values(pa: pd.DataFrame) -> pd.DataFrame:
    out = pa.copy()
    event = out["events"].fillna("")
    out["total_bases"] = event.map(
        {"single": 1, "double": 2, "triple": 3, "home_run": 4}
    ).fillna(0).astype(int)
    out["hit"] = event.isin(["single", "double", "triple", "home_run"]).astype(int)
    out["extra_base_hit"] = event.isin(["double", "triple", "home_run"]).astype(int)
    return out


def _pregame_rates(
    games: pd.DataFrame,
    player_col: str,
    prefix: str,
    pa_col: str,
    tb_col: str,
    hit_col: str,
    xbh_col: str,
) -> pd.DataFrame:
    df = games.sort_values([player_col, "game_date", "game_pk"]).copy()
    grouped = df.groupby(player_col, sort=False)
    prior_pa = grouped[pa_col].cumsum() - df[pa_col]
    prior_tb = grouped[tb_col].cumsum() - df[tb_col]
    prior_hits = grouped[hit_col].cumsum() - df[hit_col]
    prior_xbh = grouped[xbh_col].cumsum() - df[xbh_col]
    denom = prior_pa.replace(0, np.nan)
    df[f"{prefix}_tb_per_pa_prior"] = prior_tb / denom
    df[f"{prefix}_hit_rate_prior"] = prior_hits / denom
    df[f"{prefix}_xbh_rate_prior"] = prior_xbh / denom

    shifted_tb = grouped[tb_col].shift(1)
    shifted_pa = grouped[pa_col].shift(1)
    recent_tb = (
        shifted_tb.groupby(df[player_col]).rolling(10, min_periods=1).sum()
        .reset_index(level=0, drop=True)
    )
    recent_pa = (
        shifted_pa.groupby(df[player_col]).rolling(10, min_periods=1).sum()
        .reset_index(level=0, drop=True)
    )
    recent_hits = (
        grouped[hit_col].shift(1).groupby(df[player_col])
        .rolling(10, min_periods=1).sum().reset_index(level=0, drop=True)
    )
    df[f"{prefix}_recent_tb_per_pa_10"] = recent_tb / recent_pa.replace(0, np.nan)
    df[f"{prefix}_recent_hit_rate_10"] = recent_hits / recent_pa.replace(0, np.nan)
    return df


def build_tb_history(pa: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    valued = add_event_values(pa)
    batter_games = (
        valued.groupby(["game_date", "game_pk", "batter"], as_index=False)
        .agg(
            pa=("events", "count"),
            total_bases=("total_bases", "sum"),
            hits=("hit", "sum"),
            extra_base_hits=("extra_base_hit", "sum"),
        )
    )
    batter_games[TARGET_COLUMN] = (batter_games["total_bases"] >= 2).astype(int)
    batter_games = _pregame_rates(
        batter_games, "batter", "batter", "pa", "total_bases", "hits", "extra_base_hits"
    )

    pitcher_games = (
        valued.groupby(["game_date", "game_pk", "pitcher"], as_index=False)
        .agg(
            pitcher_pa=("events", "count"),
            tb_allowed=("total_bases", "sum"),
            hits_allowed=("hit", "sum"),
            xbh_allowed=("extra_base_hit", "sum"),
        )
    )
    pitcher_games = _pregame_rates(
        pitcher_games,
        "pitcher",
        "pitcher",
        "pitcher_pa",
        "tb_allowed",
        "hits_allowed",
        "xbh_allowed",
    )
    pitcher_games = pitcher_games.rename(columns=PITCHER_TB_RENAMES)
    return valued, batter_games, pitcher_games


def enrich_historical(
    model_df: pd.DataFrame, batter_games: pd.DataFrame, pitcher_games: pd.DataFrame
) -> pd.DataFrame:
    batter_cols = ["game_date", "game_pk", "batter", "total_bases", TARGET_COLUMN] + [
        c for c in TB_FEATURES if c.startswith("batter_")
    ]
    pitcher_cols = ["game_date", "game_pk", "pitcher"] + [
        c for c in TB_FEATURES if c.startswith("pitcher_")
    ]
    out = model_df.merge(
        batter_games[batter_cols], on=["game_date", "game_pk", "batter"], how="inner"
    )
    out = out.merge(
        pitcher_games[pitcher_cols].rename(columns={"pitcher": "starter_pitcher"}),
        on=["game_date", "game_pk", "starter_pitcher"],
        how="left",
    )
    return out


def enrich_forward(
    board: pd.DataFrame,
    batter_games: pd.DataFrame,
    pitcher_games: pd.DataFrame,
) -> pd.DataFrame:
    batter_snapshot = forward_rate_snapshot(
        batter_games, "batter", "batter", "pa", "total_bases", "hits", "extra_base_hits"
    )
    pitcher_snapshot = forward_rate_snapshot(
        pitcher_games, "pitcher", "pitcher", "pitcher_pa",
        "tb_allowed", "hits_allowed", "xbh_allowed"
    ).rename(columns=PITCHER_TB_RENAMES)
    batter_cols = ["batter"] + [c for c in TB_FEATURES if c.startswith("batter_")]
    pitcher_cols = ["pitcher"] + [c for c in TB_FEATURES if c.startswith("pitcher_")]
    out = board.merge(batter_snapshot[batter_cols], on="batter", how="left")
    out = out.merge(
        pitcher_snapshot[pitcher_cols],
        on="pitcher",
        how="left",
    )
    return out


def forward_rate_snapshot(
    games: pd.DataFrame,
    player_col: str,
    prefix: str,
    pa_col: str,
    tb_col: str,
    hit_col: str,
    xbh_col: str,
) -> pd.DataFrame:
    """Create as-of-today rates that include every completed historical game."""
    ordered = games.sort_values([player_col, "game_date", "game_pk"]).copy()
    career = ordered.groupby(player_col, as_index=False).agg(
        _pa=(pa_col, "sum"), _tb=(tb_col, "sum"),
        _hits=(hit_col, "sum"), _xbh=(xbh_col, "sum"),
    )
    career[f"{prefix}_tb_per_pa_prior"] = career["_tb"] / career["_pa"].replace(0, np.nan)
    career[f"{prefix}_hit_rate_prior"] = career["_hits"] / career["_pa"].replace(0, np.nan)
    career[f"{prefix}_xbh_rate_prior"] = career["_xbh"] / career["_pa"].replace(0, np.nan)

    recent = ordered.groupby(player_col, as_index=False, group_keys=False).tail(10)
    recent = recent.groupby(player_col, as_index=False).agg(
        _recent_pa=(pa_col, "sum"),
        _recent_tb=(tb_col, "sum"),
        _recent_hits=(hit_col, "sum"),
    )
    recent[f"{prefix}_recent_tb_per_pa_10"] = (
        recent["_recent_tb"] / recent["_recent_pa"].replace(0, np.nan)
    )
    recent[f"{prefix}_recent_hit_rate_10"] = (
        recent["_recent_hits"] / recent["_recent_pa"].replace(0, np.nan)
    )
    merged = career.merge(recent, on=player_col, how="left")
    generated = [
        f"{prefix}_tb_per_pa_prior",
        f"{prefix}_hit_rate_prior",
        f"{prefix}_xbh_rate_prior",
        f"{prefix}_recent_tb_per_pa_10",
        f"{prefix}_recent_hit_rate_10",
    ]
    return merged[[player_col] + generated]


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in base.get_model_feature_columns() + TB_FEATURES if c in df.columns]


def split_by_date(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.to_datetime(df["game_date"])
    train_end = pd.Timestamp(base.TRAIN_END_DATE)
    valid_end = pd.Timestamp(base.VALID_END_DATE)
    return (
        df.loc[dates <= train_end].copy(),
        df.loc[(dates > train_end) & (dates <= valid_end)].copy(),
        df.loc[dates > valid_end].copy(),
    )


def clean_matrix(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    return df[cols].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)


def evaluate(y: pd.Series, prob: np.ndarray, label: str) -> None:
    clipped = np.clip(prob, 1e-6, 1 - 1e-6)
    auc = roc_auc_score(y, clipped) if y.nunique() > 1 else float("nan")
    print(
        f"{label}: rows={len(y):,} rate={y.mean():.4f} "
        f"logloss={log_loss(y, clipped):.4f} brier={brier_score_loss(y, clipped):.4f} "
        f"auc={auc:.4f}"
    )


def fit_model(train: pd.DataFrame, valid: pd.DataFrame, cols: list[str]):
    model = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=250,
        max_leaf_nodes=20,
        min_samples_leaf=40,
        l2_regularization=1.0,
        random_state=42,
    )
    weights = base.add_recency_sample_weights(train)
    model.fit(clean_matrix(train, cols), train[TARGET_COLUMN].astype(int), sample_weight=weights)
    raw_valid = model.predict_proba(clean_matrix(valid, cols))[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_valid, valid[TARGET_COLUMN].astype(int))
    evaluate(valid[TARGET_COLUMN], raw_valid, "Validation raw")
    evaluate(valid[TARGET_COLUMN], calibrator.predict(raw_valid), "Validation calibrated")
    return model, calibrator


def save_backtest(
    model, calibrator, test: pd.DataFrame, cols: list[str]
) -> None:
    if test.empty:
        print("No out-of-sample TB rows available.")
        return
    scored = test.copy()
    scored["raw_tb_probability"] = model.predict_proba(clean_matrix(scored, cols))[:, 1]
    scored["pred_tb_probability"] = calibrator.predict(scored["raw_tb_probability"])
    evaluate(scored[TARGET_COLUMN], scored["pred_tb_probability"], "Test calibrated")
    scored.to_csv(f"{PREFIX}_scored_test_rows.csv", index=False)

    rows = []
    for top_n in [10, 20, 50]:
        ranked = (
            scored.sort_values(["game_date", "pred_tb_probability"], ascending=[True, False])
            .groupby("game_date", as_index=False, group_keys=False).head(top_n)
        )
        rows.append(
            {
                "top_n": top_n,
                "players": len(ranked),
                "wins": int(ranked[TARGET_COLUMN].sum()),
                "hit_rate": ranked[TARGET_COLUMN].mean(),
                "avg_model_probability": ranked["pred_tb_probability"].mean(),
                "brier_score": brier_score_loss(
                    ranked[TARGET_COLUMN], ranked["pred_tb_probability"]
                ),
            }
        )
    pd.DataFrame(rows).to_csv(f"{PREFIX}_backtest_summary.csv", index=False)


def make_board(
    model, calibrator, history: pd.DataFrame, pa: pd.DataFrame,
    batter_games: pd.DataFrame, pitcher_games: pd.DataFrame, cols: list[str]
) -> pd.DataFrame:
    board = base.build_forward_board_input(history, pa, base.TARGET_DATE)
    board = enrich_forward(board, batter_games, pitcher_games)
    board["raw_tb_probability"] = model.predict_proba(clean_matrix(board, cols))[:, 1]
    board["final_tb_probability"] = calibrator.predict(board["raw_tb_probability"])
    board["target_date"] = base.TARGET_DATE
    board = board.sort_values("final_tb_probability", ascending=False).reset_index(drop=True)
    board["ranking"] = np.arange(1, len(board) + 1)
    board["tb_signal"] = pd.cut(
        board["final_tb_probability"],
        bins=[-np.inf, 0.42, 0.50, 0.58, np.inf],
        labels=["Pass", "Watch", "High", "Top"],
    ).astype(str)
    path = f"{PREFIX}_board_{base.TARGET_DATE}.csv"
    board.to_csv(path, index=False)
    print(f"Saved: {path}")
    return board


def main() -> None:
    Path(base.CACHE_DIR).mkdir(exist_ok=True)
    pa = base.load_statcast_pa(
        base.FULL_DATA_START_DATE,
        base.FULL_DATA_END_DATE,
        use_cache=base.USE_CACHE,
        refresh_cache=base.REFRESH_CACHE,
    )
    _, batter_games, pitcher_games = build_tb_history(pa)
    model_df = base.build_model_dataset(pa)
    history = enrich_historical(model_df, batter_games, pitcher_games)
    history = history[pd.to_datetime(history["game_date"]) >= pd.Timestamp(base.MODEL_ROW_START_DATE)]
    train, valid, test = split_by_date(history)
    cols = feature_columns(history)
    if train.empty or valid.empty:
        raise ValueError("TB model needs non-empty training and validation date ranges.")
    print(
        f"TB rows: train={len(train):,}, validation={len(valid):,}, "
        f"test={len(test):,}; features={len(cols)}"
    )
    model, calibrator = fit_model(train, valid, cols)
    save_backtest(model, calibrator, test, cols)
    make_board(model, calibrator, history, pa, batter_games, pitcher_games, cols)


if __name__ == "__main__":
    main()
