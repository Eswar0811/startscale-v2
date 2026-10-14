import pandas as pd
import numpy as np

from sklearn.ensemble import GradientBoostingRegressor


# ============================================================
# STARTSCALE — SHADOW PREDICTIVE AUTOSCALING CONTROLLER
# ============================================================

DATASET = "v3_master_150_v3_spatial_features.csv"

TARGET = "request_to_ready_ms"

GLOBAL_P90_ADJUSTMENT_MS = 576.94


FEATURES = [
    "node_cpu_pct_v2",
    "node_memory_pct_v2",
    "worker_cpu_mean",
    "worker_memory_mean",
    "worker_memory_max",
    "worker_memory_std",
    "node_cpu_x_memory",
    "cluster_cpu_x_memory",
    "cpu_spatial_imbalance",
    "image_cache_state",
]


# ============================================================
# LOAD DATA
# ============================================================

df = pd.read_csv(DATASET)


# ============================================================
# CACHE STATE ENCODING
# ============================================================

# The dataset stores cache state as:
#
#     cold
#     warm
#
# The validated model uses:
#
#     cold = 0
#     warm = 1

df["image_cache_state"] = (
    df["image_cache_state"]
    .astype(str)
    .str.strip()
    .str.lower()
    .map({
        "cold": 0,
        "warm": 1,
    })
)


# Safety check
if df["image_cache_state"].isna().any():

    print("ERROR: Unknown image_cache_state value found.")

    print(
        df.loc[
            df["image_cache_state"].isna()
        ]
    )

    raise ValueError(
        "image_cache_state contains values other than "
        "'cold' or 'warm'."
    )


# ============================================================
# NUMERIC FEATURE CONVERSION
# ============================================================

for feature in FEATURES:

    df[feature] = pd.to_numeric(
        df[feature],
        errors="coerce"
    )


# ============================================================
# VALIDATE DATA
# ============================================================

missing = df[FEATURES + [TARGET]].isna().sum()

if missing.sum() > 0:

    print("ERROR: Missing values detected.")

    print(
        missing[
            missing > 0
        ]
    )

    raise ValueError(
        "Missing model features or target values."
    )


X = df[FEATURES].copy()

y = df[TARGET].astype(float)


# ============================================================
# TRAIN P50 MODEL
# ============================================================

p50_model = GradientBoostingRegressor(
    loss="quantile",
    alpha=0.50,
    n_estimators=200,
    learning_rate=0.05,
    max_depth=3,
    random_state=42,
)

p50_model.fit(
    X,
    y
)


# ============================================================
# TRAIN RAW P90 MODEL
# ============================================================

p90_model = GradientBoostingRegressor(
    loss="quantile",
    alpha=0.90,
    n_estimators=200,
    learning_rate=0.05,
    max_depth=3,
    random_state=42,
)

p90_model.fit(
    X,
    y
)


# ============================================================
# PREDICTION FUNCTION
# ============================================================

def predict_startup_delay(
    node_cpu_pct,
    node_memory_pct,
    worker_cpu_mean,
    worker_memory_mean,
    worker_memory_max,
    worker_memory_std,
    node_cpu_x_memory,
    cluster_cpu_x_memory,
    cpu_spatial_imbalance,
    image_cache_state,
):

    # Convert user/runtime cache state
    # into the same numerical representation
    # used during model training.

    if isinstance(
        image_cache_state,
        str
    ):

        image_cache_state = (
            image_cache_state
            .strip()
            .lower()
        )

        if image_cache_state == "cold":

            image_cache_state = 0

        elif image_cache_state == "warm":

            image_cache_state = 1

        else:

            raise ValueError(
                "image_cache_state must be "
                "'cold', 'warm', 0, or 1."
            )

    state = pd.DataFrame([{

        "node_cpu_pct_v2":
            node_cpu_pct,

        "node_memory_pct_v2":
            node_memory_pct,

        "worker_cpu_mean":
            worker_cpu_mean,

        "worker_memory_mean":
            worker_memory_mean,

        "worker_memory_max":
            worker_memory_max,

        "worker_memory_std":
            worker_memory_std,

        "node_cpu_x_memory":
            node_cpu_x_memory,

        "cluster_cpu_x_memory":
            cluster_cpu_x_memory,

        "cpu_spatial_imbalance":
            cpu_spatial_imbalance,

        "image_cache_state":
            image_cache_state,

    }])


    # Guarantee exact feature order
    state = state[FEATURES]


    p50 = float(
        p50_model.predict(state)[0]
    )

    raw_p90 = float(
        p90_model.predict(state)[0]
    )

    calibrated_p90 = (
        raw_p90
        + GLOBAL_P90_ADJUSTMENT_MS
    )


    return (
        p50,
        raw_p90,
        calibrated_p90,
    )


# ============================================================
# SHADOW DECISION
# ============================================================

def scaling_decision(
    demand_eta_ms,
    predicted_p90_ms,
    safety_margin_ms=500,
):

    required_lead_time_ms = (
        predicted_p90_ms
        + safety_margin_ms
    )


    if demand_eta_ms <= required_lead_time_ms:

        decision = "SCALE_NOW"

    elif demand_eta_ms <= (
        required_lead_time_ms + 2000
    ):

        decision = "PREPARE_SCALE"

    else:

        decision = "WAIT"


    return (
        decision,
        required_lead_time_ms,
    )


# ============================================================
# START
# ============================================================

print("=" * 80)

print(
    "STARTSCALE — SHADOW PREDICTIVE "
    "AUTOSCALING CONTROLLER"
)

print("=" * 80)


print()

print(
    f"Dataset : {DATASET}"
)

print(
    f"Samples : {len(df)}"
)

print(
    f"Features: {len(FEATURES)}"
)


print()

print("=" * 80)

print("CACHE ENCODING")

print("=" * 80)

print(
    "cold -> 0"
)

print(
    "warm -> 1"
)


print()

print("=" * 80)

print("MODEL READY")

print("=" * 80)


# ============================================================
# EXAMPLE CLUSTER STATE
# ============================================================

example_state = {

    "node_cpu_pct": 13.0,

    "node_memory_pct": 22.0,

    "worker_cpu_mean": 5.0,

    "worker_memory_mean": 22.0,

    "worker_memory_max": 23.0,

    "worker_memory_std": 1.0,

    "node_cpu_x_memory":
        13.0 * 22.0,

    "cluster_cpu_x_memory":
        5.0 * 22.0,

    "cpu_spatial_imbalance": 100.0,

    "image_cache_state": "cold",

}


# ============================================================
# PREDICT
# ============================================================

p50, raw_p90, calibrated_p90 = (
    predict_startup_delay(
        **example_state
    )
)


print()

print("=" * 80)

print("EXAMPLE CLUSTER STATE")

print("=" * 80)


for key, value in example_state.items():

    print(
        f"{key:25s}: {value}"
    )


print()

print("=" * 80)

print("STARTUP-LATENCY PREDICTION")

print("=" * 80)


print(
    f"P50 predicted delay       : "
    f"{p50:.2f} ms"
)

print(
    f"Raw P90 predicted delay   : "
    f"{raw_p90:.2f} ms"
)

print(
    f"Calibrated P90 delay      : "
    f"{calibrated_p90:.2f} ms"
)


# ============================================================
# SHADOW DECISION TESTS
# ============================================================

print()

print("=" * 80)

print("SHADOW SCALING DECISIONS")

print("=" * 80)


test_eta_values = [

    2000,

    4000,

    6000,

    8000,

    10000,

]


for demand_eta_ms in test_eta_values:

    decision, lead_time = (
        scaling_decision(
            demand_eta_ms=
                demand_eta_ms,

            predicted_p90_ms=
                calibrated_p90,
        )
    )


    print()

    print(
        f"Demand ETA        : "
        f"{demand_eta_ms:6.0f} ms"
    )

    print(
        f"Required lead time: "
        f"{lead_time:6.0f} ms"
    )

    print(
        f"Decision           : "
        f"{decision}"
    )


# ============================================================
# SAVE PREDICTION
# ============================================================

controller_summary = pd.DataFrame([{

    "p50_prediction_ms":
        p50,

    "raw_p90_prediction_ms":
        raw_p90,

    "calibrated_p90_prediction_ms":
        calibrated_p90,

    "global_p90_adjustment_ms":
        GLOBAL_P90_ADJUSTMENT_MS,

}])


controller_summary.to_csv(
    "startscale_shadow_controller_prediction.csv",
    index=False,
)


# ============================================================
# COMPLETE
# ============================================================

print()

print("=" * 80)

print("SHADOW CONTROLLER COMPLETE")

print("=" * 80)

print()

print(
    "Saved: "
    "startscale_shadow_controller_prediction.csv"
)

print()

print(
    "IMPORTANT: SHADOW MODE ONLY."
)

print(
    "No Kubernetes replicas were changed."
)