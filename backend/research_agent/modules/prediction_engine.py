"""
prediction_engine.py
--------------------
Automatically trains the best ML model for each DV found in the project.
Returns predictions, feature importance, and a 6-period forecast
(if a date column is present).
"""

import pandas as pd
import numpy as np
from typing import Optional
import warnings
warnings.filterwarnings("ignore")


def run_predictions(
    df: pd.DataFrame,
    profile: dict,
    roles: dict,
    date_col: Optional[str] = None,
) -> dict:
    """
    Main entry point.
    Returns:
      predictions  — per-row predictions for each DV
      feature_importance — top features per DV model
      forecast     — future projections (if date column exists)
      model_scores — accuracy/R² per model
    """
    output = {
        "predictions":        {},
        "feature_importance": {},
        "forecast":           {},
        "model_scores":       {},
        "errors":             [],
    }

    # Identify DVs and IVs from roles
    dv_cols  = [c for c, r in roles.items() if r == "dependent_variable" and c in df.columns]
    iv_cols  = [c for c, r in roles.items()
                if r == "independent_variable" and c in df.columns]

    if not dv_cols:
        output["errors"].append("No dependent variables identified in dataset.")
        return output

    # Build feature matrix from IVs
    X, feature_names = _build_feature_matrix(df, iv_cols, profile)

    for dv in dv_cols:
        if dv not in df.columns:
            continue
        y = df[dv].loc[X.index]
        y = y.dropna()
        X_aligned = X.loc[y.index]

        dv_type = profile["columns"].get(dv, {}).get("dtype", "numeric")

        try:
            if dv_type == "numeric":
                result = _train_regressor(X_aligned, y, feature_names, dv)
            else:
                result = _train_classifier(X_aligned, y, feature_names, dv)

            output["predictions"][dv]        = result.get("predictions", [])
            output["feature_importance"][dv] = result.get("feature_importance", [])
            output["model_scores"][dv]       = result.get("score", {})
        except Exception as e:
            output["errors"].append(f"Prediction failed for '{dv}': {str(e)}")

    # Time-series forecast if date column available
    if date_col and date_col in df.columns:
        numeric_dvs = [c for c in dv_cols
                       if profile["columns"].get(c, {}).get("dtype") == "numeric"]
        for dv in numeric_dvs[:2]:  # Forecast up to 2 DVs
            try:
                fc = _simple_forecast(df, date_col, dv)
                if fc:
                    output["forecast"][dv] = fc
            except Exception as e:
                output["errors"].append(f"Forecast failed for '{dv}': {str(e)}")

    return output


# ── Feature Engineering ───────────────────────────────────────────────────────

def _build_feature_matrix(
    df: pd.DataFrame, iv_cols: list, profile: dict
) -> tuple[pd.DataFrame, list]:
    """
    Encode categorical IVs (one-hot) and scale numeric IVs.
    Returns feature DataFrame and feature names list.
    """
    from sklearn.preprocessing import StandardScaler

    frames = []
    names  = []

    for col in iv_cols:
        col_type = profile["columns"].get(col, {}).get("dtype", "categorical")
        if col_type == "numeric":
            s = df[col].fillna(df[col].median())
            frames.append(pd.DataFrame({col: s}))
            names.append(col)
        elif col_type == "categorical":
            dummies = pd.get_dummies(df[col].fillna("Unknown"),
                                     prefix=col, drop_first=True)
            frames.append(dummies)
            names.extend(dummies.columns.tolist())

    if not frames:
        raise ValueError("No valid IV columns to build features from.")

    X = pd.concat(frames, axis=1)
    # Scale numeric columns
    num_cols = X.select_dtypes(include=[np.number]).columns
    if len(num_cols):
        scaler = StandardScaler()
        X[num_cols] = scaler.fit_transform(X[num_cols])

    return X, names


# ── Regression ────────────────────────────────────────────────────────────────

def _train_regressor(X, y, feature_names, dv_name) -> dict:
    try:
        from xgboost import XGBRegressor
        model = XGBRegressor(n_estimators=100, max_depth=5,
                             learning_rate=0.1, random_state=42,
                             verbosity=0)
    except ImportError:
        from sklearn.ensemble import GradientBoostingRegressor
        model = GradientBoostingRegressor(n_estimators=100, random_state=42)

    from sklearn.model_selection import cross_val_score
    from sklearn.metrics import r2_score, mean_absolute_error

    model.fit(X, y)
    preds = model.predict(X)
    r2    = round(r2_score(y, preds), 4)
    mae   = round(mean_absolute_error(y, preds), 4)
    cv    = cross_val_score(model, X, y, cv=5, scoring="r2")

    importance = _extract_importance(model, X.columns.tolist())

    return {
        "predictions": preds.tolist()[:100],  # First 100 rows for display
        "feature_importance": importance,
        "score": {
            "model":    "XGBoost Regressor",
            "r2":       r2,
            "mae":      mae,
            "cv_r2_mean": round(cv.mean(), 4),
            "cv_r2_std":  round(cv.std(), 4),
            "label":    f"R² = {r2} | MAE = {mae} | CV R² = {round(cv.mean(),4)}",
        },
    }


# ── Classification ────────────────────────────────────────────────────────────

def _train_classifier(X, y, feature_names, dv_name) -> dict:
    try:
        from xgboost import XGBClassifier
        from sklearn.preprocessing import LabelEncoder
        le = LabelEncoder()
        y_enc = le.fit_transform(y)
        model = XGBClassifier(n_estimators=100, max_depth=5,
                              learning_rate=0.1, random_state=42,
                              verbosity=0, use_label_encoder=False,
                              eval_metric="logloss")
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.preprocessing import LabelEncoder
        le = LabelEncoder()
        y_enc = le.fit_transform(y)
        model = GradientBoostingClassifier(n_estimators=100, random_state=42)

    from sklearn.model_selection import cross_val_score
    from sklearn.metrics import accuracy_score, f1_score

    model.fit(X, y_enc)
    preds_enc = model.predict(X)
    preds     = le.inverse_transform(preds_enc)
    acc       = round(accuracy_score(y_enc, preds_enc), 4)
    f1        = round(f1_score(y_enc, preds_enc, average="weighted"), 4)
    cv        = cross_val_score(model, X, y_enc, cv=5, scoring="accuracy")
    importance = _extract_importance(model, X.columns.tolist())

    return {
        "predictions": preds.tolist()[:100],
        "feature_importance": importance,
        "score": {
            "model":    "XGBoost Classifier",
            "accuracy": acc,
            "f1":       f1,
            "cv_acc_mean": round(cv.mean(), 4),
            "label":    f"Accuracy = {round(acc*100,1)}% | F1 = {f1} | CV Acc = {round(cv.mean()*100,1)}%",
        },
    }


# ── Feature Importance ────────────────────────────────────────────────────────

def _extract_importance(model, col_names: list) -> list:
    try:
        fi = model.feature_importances_
        pairs = sorted(zip(col_names, fi), key=lambda x: x[1], reverse=True)
        return [{"feature": f, "importance": round(float(v), 4)}
                for f, v in pairs[:15]]
    except Exception:
        return []


# ── Time-Series Forecast ──────────────────────────────────────────────────────

def _simple_forecast(df: pd.DataFrame, date_col: str, dv_col: str) -> dict:
    """
    Aggregates DV by month and fits a simple linear trend
    for 6 future periods. Returns historical + forecast series.
    """
    df2 = df[[date_col, dv_col]].copy()
    df2[date_col] = pd.to_datetime(df2[date_col], errors="coerce")
    df2 = df2.dropna()
    df2 = df2.set_index(date_col).resample("ME")[dv_col].mean().dropna()

    if len(df2) < 6:
        return {}

    x = np.arange(len(df2))
    y = df2.values
    slope, intercept = np.polyfit(x, y, 1)

    forecast_periods = 6
    future_x = np.arange(len(df2), len(df2) + forecast_periods)
    forecast_vals = slope * future_x + intercept

    last_date = df2.index[-1]
    future_dates = pd.date_range(start=last_date, periods=forecast_periods+1,
                                 freq="ME")[1:]

    return {
        "historical": {
            "dates":  [str(d.date()) for d in df2.index],
            "values": [round(v, 4) for v in df2.values],
        },
        "forecast": {
            "dates":  [str(d.date()) for d in future_dates],
            "values": [round(v, 4) for v in forecast_vals],
        },
        "trend": {
            "slope":      round(slope, 4),
            "direction":  "Upward" if slope > 0 else "Downward",
            "monthly_change": round(slope, 4),
        },
        "dv": dv_col,
    }
