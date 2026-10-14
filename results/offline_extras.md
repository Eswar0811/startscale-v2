## SHAP attribution (mean |SHAP|, seconds, LightGBM q0.90, measured events)

worker_cpu_mean          0.513
cpu_spatial_imbalance    0.160
node_cpu_pct_v2          0.125
worker_memory_std        0.106
cold                     0.083
worker_memory_mean       0.075
node_memory_pct_v2       0.043
worker_memory_max        0.035

## Experiment I: transfer across nodes (train others -> test node)

          test_node  n  MAE_q50  MAE_global_median  coverage_q90  nominal
autoscaling-worker3 39    0.483              0.727         0.949      0.9
 autoscaling-worker 81    0.695              0.775         0.802      0.9
autoscaling-worker2 30    0.616              0.826         1.000      0.9

## Drift experiment (twin analogue of mid-run image change)

change at event 1000; ADWIN fired at event 1055 (detection latency 55 events)
post-detection q90 coverage over next 400 events: stale model 0.41, refit 0.65 (nominal 0.90)

Detection latency is reported in events (~pod creations); a wall-clock figure needs the cluster run.