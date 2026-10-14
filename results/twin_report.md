## Experiment C/D: controller comparison (mean over workloads×seeds; twin)

### profile = measured

                                       slo_violation_rate    p99_ms  replica_seconds  sign_changes_per_min
arm                              tau                                                                      
fixed_lead                       NaN                0.030  1360.816        22210.500                 0.184
forecast_only                    NaN                0.015  1538.333        21431.625                 0.181
hpa_t0.5                         NaN                0.036  1300.000        34407.750                 0.112
hpa_t0.6                         NaN                0.041  1300.000        28768.125                 0.145
hpa_t0.7                         NaN                0.043  1300.000        24858.000                 0.167
hpa_t0.8                         NaN                0.046  1349.057        21989.250                 0.132
keda                             NaN                0.044  1307.280        23266.125                 0.171
startscale                       0.50               0.015  1457.274        20946.750                 0.182
                                 0.90               0.014  1428.670        21048.000                 0.176
                                 0.95               0.014  1487.836        21050.250                 0.180
startscale[oracle10]             0.50               0.000    67.188        21151.500                 0.273
                                 0.90               0.000    67.188        21156.750                 0.268
                                 0.95               0.000    67.188        21180.000                 0.268
startscale_timing_only           0.50               0.015  1457.274        21003.375                 0.178
                                 0.90               0.014  1428.670        21043.125                 0.175
                                 0.95               0.015  1487.836        21065.250                 0.180
startscale_timing_only[oracle10] 0.50               0.000    55.250        21318.375                 0.281
                                 0.90               0.000    55.250        21349.875                 0.277
                                 0.95               0.000    55.250        21350.625                 0.277

Mann–Whitney U, StartScale(τ=0.9) violation rate < baseline (n=40 runs each), Holm-adjusted:

- vs fixed_lead: Δmean=-0.0155, Cliff's δ=-0.01, p_holm=1
- vs forecast_only: Δmean=-0.0004, Cliff's δ=+0.01, p_holm=1
- vs hpa_t0.5: Δmean=-0.0222, Cliff's δ=+0.08, p_holm=1
- vs hpa_t0.6: Δmean=-0.0264, Cliff's δ=+0.08, p_holm=1
- vs hpa_t0.7: Δmean=-0.0287, Cliff's δ=+0.08, p_holm=1
- vs hpa_t0.8: Δmean=-0.0320, Cliff's δ=-0.04, p_holm=1
- vs keda: Δmean=-0.0303, Cliff's δ=+0.06, p_holm=1

### profile = extended_cold

                                       slo_violation_rate    p99_ms  replica_seconds  sign_changes_per_min
arm                              tau                                                                      
fixed_lead                       NaN                0.059  1541.064        22907.625                 0.188
forecast_only                    NaN                0.040  1832.480        21490.875                 0.192
hpa_t0.5                         NaN                0.039  1304.970        34421.625                 0.112
hpa_t0.6                         NaN                0.061  1306.256        28777.875                 0.144
hpa_t0.7                         NaN                0.067  1310.158        24850.500                 0.157
hpa_t0.8                         NaN                0.077  1587.503        22000.125                 0.132
keda                             NaN                0.074  1334.339        23239.500                 0.167
startscale                       0.50               0.032  1632.802        22488.375                 0.190
                                 0.90               0.031  1668.993        23093.625                 0.216
                                 0.95               0.029  1603.830        23770.500                 0.211
startscale[oracle10]             0.50               0.014  1326.321        22236.750                 0.278
                                 0.90               0.003   254.360        22018.500                 0.296
                                 0.95               0.003   304.667        22393.125                 0.303
startscale_timing_only           0.50               0.026  1685.009        22308.375                 0.202
                                 0.90               0.023  1744.167        22759.500                 0.198
                                 0.95               0.022  1589.558        23362.125                 0.208
startscale_timing_only[oracle10] 0.50               0.009   516.419        21712.125                 0.292
                                 0.90               0.002   172.899        21850.875                 0.290
                                 0.95               0.001   106.745        22312.125                 0.289

Mann–Whitney U, StartScale(τ=0.9) violation rate < baseline (n=40 runs each), Holm-adjusted:

- vs fixed_lead: Δmean=-0.0282, Cliff's δ=-0.09, p_holm=1
- vs forecast_only: Δmean=-0.0091, Cliff's δ=-0.07, p_holm=1
- vs hpa_t0.5: Δmean=-0.0087, Cliff's δ=+0.13, p_holm=1
- vs hpa_t0.6: Δmean=-0.0303, Cliff's δ=+0.07, p_holm=1
- vs hpa_t0.7: Δmean=-0.0366, Cliff's δ=+0.05, p_holm=1
- vs hpa_t0.8: Δmean=-0.0462, Cliff's δ=-0.08, p_holm=1
- vs keda: Δmean=-0.0431, Cliff's δ=+0.04, p_holm=1

## Experiment E: horizon-matching (twin, all-cold cluster, timing lever only)

H                      -1.0     5.0     15.0    30.0    60.0    90.0    120.0   180.0
workload        noise                                                                
ramp            0.0     0.000   0.000   0.000   0.000   0.000   0.000   0.000   0.000
                0.1     0.000   0.000   0.000   0.000   0.000   0.000   0.000   0.000
repeated_bursts 0.0     0.073   0.204   0.204   0.099   0.099   0.084   0.046   0.003
                0.1     0.021   0.215   0.215   0.084   0.056   0.024   0.003   0.000
(H = -1 is the matched horizon Δ_τ + T_control)

## Experiment G: ablations (τ=0.9; twin)

### measured

                                  slo_violation_rate  replica_seconds  sign_changes_per_min  prepull_mb
arm                                                                                                    
startscale:full                               0.0141        21048.000                0.1758       240.0
startscale:no_affinity                        0.0141        21043.125                0.1750       180.0
startscale:no_compensation                    0.0257        20572.500                0.1858       270.0
startscale:no_conformal                       0.0141        21042.375                0.1775       240.0
startscale:no_ledger(count_all)               0.0141        21048.000                0.1758       240.0
startscale:no_ledger(ready_only)              0.0141        21048.000                0.1758       240.0
startscale:no_placement                       0.0141        21043.125                0.1750         0.0
startscale:no_prepull                         0.0141        21048.000                0.1758         0.0

### extended_cold

                                  slo_violation_rate  replica_seconds  sign_changes_per_min  prepull_mb
arm                                                                                                    
startscale:full                               0.0305        23093.625                0.2158       900.0
startscale:no_affinity                        0.0225        22754.625                0.2083       570.0
startscale:no_compensation                    0.0423        21956.625                0.1833      1335.0
startscale:no_conformal                       0.0306        23097.000                0.2158       885.0
startscale:no_ledger(count_all)               0.0310        22860.750                0.2000       915.0
startscale:no_ledger(ready_only)              0.0299        23724.750                0.2217       870.0
startscale:no_placement                       0.0230        22759.500                0.1983         0.0
startscale:no_prepull                         0.0302        23106.375                0.2050         0.0

## Experiment F: placement steering under cold caches (twin analogue; real-cluster run pending)

                                          slo_violation_rate    p95_ms  deficit_seconds  replica_seconds  prepull_mb  pull_mb
workload        arm                                                                                                          
repeated_bursts F1_blind                               0.127  5050.000            103.6          28914.0         0.0   1800.0
                F2_timing_only                         0.089  4150.857             69.4          31971.0         0.0   2040.0
                F3_timing_plus_placement               0.108  5050.000             89.8          33168.0       120.0   2040.0
spike           F1_blind                               0.149  5050.000             82.8          15936.0         0.0   1800.0
                F2_timing_only                         0.067  3325.220             35.6          19065.0         0.0   2040.0
                F3_timing_plus_placement               0.112  5050.000             68.0          20343.0       120.0   2040.0
trace_worldcup  F1_blind                               0.000    50.000              0.0          23823.0         0.0   1800.0
                F2_timing_only                         0.000    50.000              0.0          24351.0         0.0   1920.0
                F3_timing_plus_placement               0.000    50.000              0.0          24399.0      1440.0   2520.0

## Experiment J: adversarial repeated bursts (period swept; twin)

                        slo_violation_rate  replica_seconds  pull_mb  sign_changes_per_min
period arm                                                                                
60.0   hpa_t0.6                      0.054          45138.0   1800.0                 0.073
       startscale_t0.5               0.041          35277.0   1800.0                 0.373
       startscale_t0.9               0.037          36597.0   1800.0                 0.287
90.0   hpa_t0.6                      0.063          45276.0   1800.0                 0.113
       startscale_t0.5               0.041          39966.0   1800.0                 0.613
       startscale_t0.9               0.041          42342.0   1800.0                 0.587
120.0  hpa_t0.6                      0.055          45315.0   1800.0                 0.087
       startscale_t0.5               0.054          39294.0   1800.0                 0.433
       startscale_t0.9               0.077          41640.0   1800.0                 0.433
150.0  hpa_t0.6                      0.067          45219.0   1800.0                 0.093
       startscale_t0.5               0.062          41331.0   1800.0                 0.580
       startscale_t0.9               0.081          44490.0   1800.0                 0.647
200.0  hpa_t0.6                      0.086          45162.0   1800.0                 0.353
       startscale_t0.5               0.081          37938.0   1800.0                 0.567
       startscale_t0.9               0.105          40806.0   1800.0                 0.567
300.0  hpa_t0.6                      0.261          41646.0   1800.0                 0.333
       startscale_t0.5               0.087          33756.0   1800.0                 0.413
       startscale_t0.9               0.124          35145.0   3240.0                 0.413
