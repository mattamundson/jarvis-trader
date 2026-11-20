#!/usr/bin/env python3
"""Walk-forward backtest of balance-vs-trend predictors.

Models: univariate thresholds, depth-3 tree, logistic regression.
Scorecard uses ONLY holdout-validated rules (train 60% → test 40%).
VIX cutoffs are treated as overfit risk (Mechaniq); a priori buckets only.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from labels import VARIANTS

REGIME = Path(__file__).resolve().parent
DATA = REGIME / "data" / "sessions_labeled.csv"
OUT = REGIME / "reports" / "backtest_results.json"

PRE_OPEN = [
    "ovn_atr",
    "gap_prior_range",
    "gap_in_range",
    "vix_prior",
    "vix_chg",
    "vix9_ratio",
    "is_event",
    "is_nfp",
    "opex",
    "dow",
    "prior_was_trend",
    "prior_was_balance",
    "prior_nr4",
    "prior_nr7",
    "prior_inside",
    "prior_range_atr",
    "gex_sign",
]

STAGE_IB = ["ib_atr", "ib_ovn", "f30_range", "open_drive_atr", "otf_count",
            "is_open_drive", "is_open_test_drive", "is_open_rejection_reverse", "is_open_auction"]


def _trend_y(df: pd.DataFrame, col: str = "label_primary") -> np.ndarray:
    return (df[col] == "trend").astype(int).values


def bucket_trend_rates(df, feature, edges, label_col="label_primary"):
    cols = [feature, label_col]
    if "range_atr" in df.columns:
        cols.append("range_atr")
    sub = df[cols].dropna(subset=[feature, label_col])
    if sub.empty:
        return []
    cats = pd.cut(sub[feature], bins=edges, include_lowest=True)
    out = []
    for cat, g in sub.groupby(cats, observed=True):
        n = len(g)
        row = {
            "bucket": str(cat),
            "n": int(n),
            "trend_rate": round(float((g[label_col] == "trend").mean()), 3),
            "balance_rate": round(float((g[label_col] == "balance").mean()), 3),
        }
        if "range_atr" in g.columns:
            row["mean_range_atr"] = round(float(g["range_atr"].mean()), 3)
        out.append(row)
    return out


def binary_rate(df, feature, label_col="label_primary"):
    cols = [feature, label_col]
    if "range_atr" in df.columns:
        cols.append("range_atr")
    sub = df[cols].dropna(subset=[feature, label_col])
    out = []
    for val, g in sub.groupby(feature):
        n = len(g)
        row = {
            "value": int(val) if isinstance(val, (int, np.integer, float)) and float(val).is_integer() else val,
            "n": int(n),
            "trend_rate": round(float((g[label_col] == "trend").mean()), 3),
            "balance_rate": round(float((g[label_col] == "balance").mean()), 3),
        }
        if "range_atr" in g.columns:
            row["mean_range_atr"] = round(float(g["range_atr"].mean()), 3)
        out.append(row)
    return out


def categorical_rate(df, feature, label_col="label_primary"):
    sub = df[[feature, label_col, "range_atr"]].dropna(subset=[feature, label_col]) if "range_atr" in df.columns else df[[feature, label_col]].dropna()
    out = []
    for val, g in sub.groupby(feature):
        n = len(g)
        row = {
            "value": val,
            "n": int(n),
            "trend_rate": round(float((g[label_col] == "trend").mean()), 3),
            "balance_rate": round(float((g[label_col] == "balance").mean()), 3),
        }
        if "range_atr" in g.columns:
            row["mean_range_atr"] = round(float(g["range_atr"].mean()), 3)
        out.append(row)
    return out


# ---- logistic / tree (same as before, compact) ----
def _sigmoid(z):
    z = np.clip(z, -30, 30)
    return 1.0 / (1.0 + np.exp(-z))


def fit_logistic(X, y, l2=1.0, iters=400, lr=0.05):
    n, p = X.shape
    w = np.zeros(p + 1)
    Xb = np.column_stack([X, np.ones(n)])
    for _ in range(iters):
        p_hat = _sigmoid(Xb @ w)
        grad = Xb.T @ (p_hat - y) / n + l2 * np.r_[w[:-1], 0.0] / n
        w -= lr * grad
    return w


def predict_logistic(X, w):
    Xb = np.column_stack([X, np.ones(len(X))])
    return _sigmoid(Xb @ w)


def _gini(y):
    if len(y) == 0:
        return 0.0
    p = y.mean()
    return 1.0 - p * p - (1 - p) * (1 - p)


def _best_split(X, y, feat_idx):
    vals = np.unique(X[:, feat_idx])
    if len(vals) < 2:
        return None, 0.0
    cands = (vals[:-1] + vals[1:]) / 2.0
    if len(cands) > 40:
        cands = np.unique(np.quantile(X[:, feat_idx], np.linspace(0.05, 0.95, 20)))
    parent = _gini(y) * len(y)
    best_t, best_gain = None, 0.0
    for t in cands:
        left = y[X[:, feat_idx] <= t]
        right = y[X[:, feat_idx] > t]
        if len(left) < 20 or len(right) < 20:
            continue
        gain = parent - (_gini(left) * len(left) + _gini(right) * len(right))
        if gain > best_gain:
            best_gain, best_t = gain, float(t)
    return best_t, best_gain


def fit_tree(X, y, feature_names, max_depth=3):
    def build(idxs, depth):
        yy = y[idxs]
        node = {"n": int(len(yy)), "trend_rate": round(float(yy.mean()), 3), "depth": depth}
        if depth >= max_depth or len(yy) < 40 or yy.mean() in (0.0, 1.0):
            node["leaf"] = True
            node["pred"] = float(yy.mean())
            return node
        best = (None, None, 0.0)
        for j in range(X.shape[1]):
            t, gain = _best_split(X[idxs], yy, j)
            if t is not None and gain > best[2]:
                best = (j, t, gain)
        if best[0] is None:
            node["leaf"] = True
            node["pred"] = float(yy.mean())
            return node
        j, t, _ = best
        left_mask = X[idxs, j] <= t
        node["leaf"] = False
        node["feature"] = feature_names[j]
        node["threshold"] = round(float(t), 4)
        node["left"] = build(idxs[left_mask], depth + 1)
        node["right"] = build(idxs[~left_mask], depth + 1)
        return node
    return build(np.arange(len(y)), 0)


def predict_tree(tree, row):
    node = tree
    while not node.get("leaf", True):
        val = row.get(node["feature"])
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return node["trend_rate"]
        node = node["left"] if val <= node["threshold"] else node["right"]
    return node["pred"]


def _impute_matrix(df, cols, medians=None):
    medians = dict(medians or {})
    X = np.zeros((len(df), len(cols)))
    for j, c in enumerate(cols):
        s = df[c]
        if c not in medians:
            medians[c] = float(s.median()) if s.notna().any() else 0.0
        X[:, j] = s.fillna(medians[c]).values
    return X, medians


def walk_forward(df, features, label_col="label_primary", train_frac=0.60, n_folds=4):
    n = len(df)
    min_train = int(n * train_frac)
    fold_size = max(40, (n - min_train) // n_folds)
    folds = []
    all_pred_lr = np.full(n, np.nan)
    all_pred_tree = np.full(n, np.nan)
    all_y = _trend_y(df, label_col)
    start = min_train
    fold_i = 0
    while start < n and fold_i < n_folds:
        end = min(n, start + fold_size)
        train, test = df.iloc[:start], df.iloc[start:end]
        y_tr = _trend_y(train, label_col)
        y_te = _trend_y(test, label_col)
        cols = [c for c in features if c in df.columns]
        Xtr, med = _impute_matrix(train, cols)
        Xte, _ = _impute_matrix(test, cols, medians=med)
        mu, sd = Xtr.mean(0), Xtr.std(0)
        sd[sd < 1e-9] = 1.0
        w = fit_logistic((Xtr - mu) / sd, y_tr.astype(float))
        p_lr = predict_logistic((Xte - mu) / sd, w)
        tree = fit_tree(Xtr, y_tr.astype(float), cols, max_depth=3)
        p_tree = np.array([predict_tree(tree, test.iloc[i][cols].to_dict()) for i in range(len(test))])
        all_pred_lr[start:end] = p_lr
        all_pred_tree[start:end] = p_tree

        def acc(p, y, thr=0.5):
            return float(((p >= thr).astype(int) == y).mean())

        folds.append({
            "fold": fold_i,
            "train_n": int(len(train)),
            "test_n": int(len(test)),
            "test_span": [test["date"].iloc[0], test["date"].iloc[-1]],
            "base_rate_train": round(float(y_tr.mean()), 3),
            "base_rate_test": round(float(y_te.mean()), 3),
            "lr_acc": round(acc(p_lr, y_te), 3),
            "tree_acc": round(acc(p_tree, y_te), 3),
            "tree": tree,
        })
        start = end
        fold_i += 1

    mask = ~np.isnan(all_pred_lr)
    y_oos = all_y[mask]
    base_maj = max(float(y_oos.mean()), 1 - float(y_oos.mean()))
    lr_acc = float(((all_pred_lr[mask] >= 0.5).astype(int) == y_oos).mean())
    tree_acc = float(((all_pred_tree[mask] >= 0.5).astype(int) == y_oos).mean())

    oos_df = df.loc[mask].copy()
    oos_df["p_lr"] = all_pred_lr[mask]
    oos_df["y"] = y_oos
    oos_df["decile"] = pd.qcut(oos_df["p_lr"], 10, duplicates="drop")
    cal = []
    for dec, g in oos_df.groupby("decile", observed=True):
        cal.append({
            "decile": str(dec), "n": int(len(g)),
            "mean_p": round(float(g["p_lr"].mean()), 3),
            "realized_trend_rate": round(float(g["y"].mean()), 3),
        })
    return {
        "n_oos": int(mask.sum()),
        "oos_trend_rate": round(float(y_oos.mean()), 3),
        "majority_baseline_acc": round(base_maj, 3),
        "logistic_oos_acc": round(lr_acc, 3),
        "tree_oos_acc": round(tree_acc, 3),
        "logistic_lift_vs_majority": round(lr_acc - base_maj, 3),
        "tree_lift_vs_majority": round(tree_acc - base_maj, 3),
        "folds": [{k: v for k, v in f.items() if k != "tree"} for f in folds],
        "final_tree": folds[-1]["tree"] if folds else None,
        "calibration_deciles": cal,
    }


def score_row(row) -> int:
    """Holdout-validated point rules (train lifts that also held OOS direction).

    Positive → trend lean (avoid naked short premium).
    Negative → balance lean (decay / sell-premium candidate — still cost-aware).

    VIX: a priori buckets only. VIX>=25 FAILED holdout → zero points.
    prior_nr4 / prior_inside: NO points (no positive lift in full sample).
    """
    s = 0
    if row.get("is_event") == 1:
        s += 2
    dow = row.get("dow")
    if dow in (2, 3):
        s += 1
    if dow == 0:
        s -= 2
    vx = row.get("vix_prior")
    if pd.notna(vx):
        if vx < 15:
            s -= 1          # confirmed OOS: balance lean
        elif 15 <= vx < 20:
            s += 1          # confirmed OOS: mild trend lean
        elif 20 <= vx < 25:
            s -= 1          # confirmed OOS: mild balance lean
        # >=25: FAILED holdout — no points (Mechaniq overfit warning)
    oa = row.get("ovn_atr")
    if pd.notna(oa):
        if oa < 0.5:
            s -= 1
        elif 0.5 <= oa < 0.75:
            s += 1
    if row.get("opex") == 1:
        s -= 1
    ch = row.get("vix_chg")
    if pd.notna(ch) and ch >= 2:
        s -= 1
    gp = row.get("gap_prior_range")
    if pd.notna(gp) and gp >= 0.5:
        s += 1
    return int(s)


def score_row_stage2(row) -> int:
    """Add IB / open-type points available ~09:30 CT (empirical signs)."""
    s = score_row(row)
    ib = row.get("ib_atr")
    if pd.notna(ib):
        if ib <= 0.35:
            s += 2  # narrow IB → higher trend-label rate (Dalton)
        elif 0.50 < ib <= 0.70:
            s -= 1  # mid-wide IB: lower trend-label rate
    # open_drive empirically LOWER trend rate in our sample → balance lean
    if row.get("is_open_drive") == 1:
        s -= 1
    if row.get("is_open_auction") == 1:
        s += 1
    if row.get("is_open_test_drive") == 1:
        s += 1
    otf = row.get("otf_count")
    if pd.notna(otf) and otf >= 2:
        s += 1
    return int(s)


def oos_score_eval(df, train_frac=0.6, stage2=False):
    split = int(len(df) * train_frac)
    test = df.iloc[split:].copy()
    fn = score_row_stage2 if stage2 else score_row
    test["_s"] = [fn(r) for _, r in test.iterrows()]
    buckets = []
    for label, lo, hi, disp in [
        ("low", -99, 0, "0-3"),
        ("mid", 1, 2, "4-6"),
        ("high", 3, 99, "7-10"),
    ]:
        g = test[(test["_s"] >= lo) & (test["_s"] <= hi)]
        n = len(g)
        buckets.append({
            "bucket": label,
            "display": disp,
            "raw_range": [lo, hi],
            "n": int(n),
            "trend_rate": round(float((g["label_primary"] == "trend").mean()), 3) if n else None,
            "balance_rate": round(float((g["label_primary"] == "balance").mean()), 3) if n else None,
            "mean_range_atr": round(float(g["range_atr"].mean()), 3) if n else None,
        })
    return {
        "train_n": split,
        "oos_n": int(len(test)),
        "oos_base_trend": round(float((test["label_primary"] == "trend").mean()), 3),
        "oos_base_balance": round(float((test["label_primary"] == "balance").mean()), 3),
        "buckets": buckets,
        "stage2": stage2,
    }


def vix_holdout_check(df, train_frac=0.6):
    """A priori VIX buckets: report train vs OOS. Flag if OOS fails to confirm."""
    split = int(len(df) * train_frac)
    edges = [0, 15, 20, 25, 100]
    labels = ["<15", "15-20", "20-25", ">=25"]
    out = []
    for i, lab in enumerate(labels):
        lo, hi = edges[i], edges[i + 1]
        def rates(part):
            g = part[(part["vix_prior"] >= lo) & (part["vix_prior"] < hi)]
            n = len(g)
            return {
                "n": int(n),
                "trend_rate": round(float((g["label_primary"] == "trend").mean()), 3) if n else None,
                "balance_rate": round(float((g["label_primary"] == "balance").mean()), 3) if n else None,
            }
        tr, te = rates(df.iloc[:split]), rates(df.iloc[split:])
        # "confirm" if OOS direction of lift vs base matches train and |lift|>=0.03 with n>=30
        base_tr = float((df.iloc[:split]["label_primary"] == "trend").mean())
        base_te = float((df.iloc[split:]["label_primary"] == "trend").mean())
        lift_tr = (tr["trend_rate"] - base_tr) if tr["trend_rate"] is not None else None
        lift_te = (te["trend_rate"] - base_te) if te["trend_rate"] is not None else None
        confirmed = (
            lift_tr is not None and lift_te is not None
            and te["n"] >= 30
            and abs(lift_te) >= 0.02
            and (lift_tr * lift_te > 0)
        )
        out.append({
            "bucket": lab,
            "train": tr,
            "oos": te,
            "lift_train": round(lift_tr, 3) if lift_tr is not None else None,
            "lift_oos": round(lift_te, 3) if lift_te is not None else None,
            "holdout_confirmed": confirmed,
            "note": None if confirmed else "FAILED holdout or thin OOS — do not gate selling on this cut alone",
        })
    return {
        "protocol": "a priori buckets [0,15,20,25,100]; no searched thresholds",
        "mechaniq_warning": "Searched VIX>=17/20 IC gates overfit (Mechaniq Lab PBO 0.43). We only report fixed buckets.",
        "buckets": out,
    }


def sensitivity(df):
    out = {}
    for p in VARIANTS:
        col = f"label_{p.name}"
        if col not in df.columns:
            continue
        vc = df[col].value_counts(normalize=True).to_dict()
        out[p.name] = {
            "params": {
                "outer_frac": p.outer_frac,
                "trend_range_mult": p.trend_range_mult,
                "balance_mid_frac": p.balance_mid_frac,
                "balance_range_mult": p.balance_range_mult,
            },
            "rates": {k: round(float(v), 3) for k, v in vc.items()},
            "n": int(df[col].notna().sum()),
        }
    return out


def univariate_report(df):
    rep = {
        "ovn_atr": bucket_trend_rates(df, "ovn_atr", [0, 0.5, 0.75, 1.0, 1.5, 10]),
        "ib_atr": bucket_trend_rates(df, "ib_atr", [0, 0.35, 0.50, 0.70, 1.0, 3]),
        "gap_prior_range": bucket_trend_rates(df, "gap_prior_range", [0, 0.15, 0.30, 0.50, 1.0, 5]),
        "vix_prior": bucket_trend_rates(df, "vix_prior", [0, 15, 20, 25, 35, 100]),
        "vix9_ratio": bucket_trend_rates(df, "vix9_ratio", [0, 0.9, 1.0, 1.05, 1.2, 3]),
        "vix_chg": bucket_trend_rates(df, "vix_chg", [-20, -2, 0, 2, 5, 30]),
        "open_drive_atr": bucket_trend_rates(df, "open_drive_atr", [0, 0.15, 0.30, 0.50, 1.0, 3]),
        "otf_count": binary_rate(df.assign(otf_ge2=(df["otf_count"] >= 2).astype(int)), "otf_ge2")
        if "otf_count" in df.columns else [],
        "gap_in_range": binary_rate(df, "gap_in_range"),
        "is_event": binary_rate(df, "is_event"),
        "is_nfp": binary_rate(df, "is_nfp"),
        "opex": binary_rate(df, "opex"),
        "prior_was_trend": binary_rate(df, "prior_was_trend"),
        "prior_was_balance": binary_rate(df, "prior_was_balance"),
        "prior_nr4": binary_rate(df, "prior_nr4"),
        "prior_nr7": binary_rate(df, "prior_nr7"),
        "prior_inside": binary_rate(df, "prior_inside"),
        "dow": binary_rate(df, "dow"),
        "open_type": categorical_rate(df, "open_type"),
    }
    if df["gex_available"].sum() >= 5:
        rep["gex_sign"] = binary_rate(df[df["gex_available"] == 1], "gex_sign")
        rep["gex_note"] = f"n={int(df['gex_available'].sum())} overnight-carry snapshots only — too thin for OOS gate"
    else:
        rep["gex_sign"] = {"note": "insufficient GEX history", "n": int(df["gex_available"].sum())}
    return rep


def top_lifts(uni, base, min_n=40):
    top = []
    for name, buckets in uni.items():
        if not isinstance(buckets, list):
            continue
        for b in buckets:
            tr = b.get("trend_rate")
            n = b.get("n") or 0
            if tr is None or n < min_n:
                continue
            top.append({
                "feature": name,
                "bucket": b.get("bucket", b.get("value")),
                "n": n,
                "trend_rate": tr,
                "balance_rate": b.get("balance_rate"),
                "mean_range_atr": b.get("mean_range_atr"),
                "lift": round(tr - base, 3),
            })
    top.sort(key=lambda x: abs(x["lift"]), reverse=True)
    return top


def main():
    df = pd.read_csv(DATA)
    base = float((df["label_primary"] == "trend").mean())
    feats = [c for c in PRE_OPEN if c in df.columns and c != "gex_sign"]
    # gex too sparse for model matrix

    uni = univariate_report(df)
    sens = sensitivity(df)
    wf_pre = walk_forward(df, feats)
    stage2_feats = feats + [c for c in STAGE_IB if c in df.columns]
    wf_s2 = walk_forward(df, stage2_feats)
    oos_pre = oos_score_eval(df, stage2=False)
    oos_s2 = oos_score_eval(df, stage2=True)
    vix_check = vix_holdout_check(df)
    top = top_lifts(uni, base)

    results = {
        "n": int(len(df)),
        "span": [df["date"].iloc[0], df["date"].iloc[-1]],
        "base_trend_rate": round(base, 3),
        "base_balance_rate": round(float((df["label_primary"] == "balance").mean()), 3),
        "sensitivity": sens,
        "univariate": uni,
        "top_lifts": top[:20],
        "walk_forward_preopen": wf_pre,
        "walk_forward_stage2_ib": {k: v for k, v in wf_s2.items() if k != "final_tree"},
        "oos_score_preopen": oos_pre,
        "oos_score_stage2": oos_s2,
        "vix_holdout": vix_check,
        "features_preopen": feats,
        "features_stage2": stage2_feats,
        "cost_caveat_vilkov": (
            "Vilkov 0DTE study (SSRN 4641356 / github.com/vilkovgr/0dte-strategies): "
            "iron condors/butterflies can show positive GROSS Sharpe but after the Aug 2026 "
            "bid-ask cost correction, no strategy retains positive NET Sharpe. "
            "Day-type skill ≠ automatic premium-selling edge. Paper only until options P&L exists."
        ),
        "gex_caveat": (
            f"Only {int(df['gex_available'].sum())} sessions have overnight GEX carry; "
            "treat gex_sign as live overlay when fresh (<60m), not as fitted historical weight."
        ),
    }
    # strip tree from preopen folds dump size — keep final_tree
    results["walk_forward_preopen"] = {
        k: v for k, v in wf_pre.items()
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "out": str(OUT),
        "n": results["n"],
        "base_trend": results["base_trend_rate"],
        "lr_oos_pre": wf_pre["logistic_oos_acc"],
        "lr_oos_s2": wf_s2["logistic_oos_acc"],
        "majority": wf_pre["majority_baseline_acc"],
        "top8": top[:8],
        "oos_score_preopen": oos_pre["buckets"],
        "oos_score_stage2": oos_s2["buckets"],
        "vix_holdout_confirmed": [b["bucket"] for b in vix_check["buckets"] if b["holdout_confirmed"]],
        "vix_holdout_failed": [b["bucket"] for b in vix_check["buckets"] if not b["holdout_confirmed"]],
    }, indent=2))


if __name__ == "__main__":
    main()
