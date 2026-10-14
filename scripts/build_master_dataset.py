"""Assemble shards into data/startscale_readiness_v5.parquet (only validated, status==ok rows)."""
import pathlib, sys
import pandas as pd
shards = [pathlib.Path(p) / "events.csv" for p in sys.argv[1:]]
d = pd.concat([pd.read_csv(s) for s in shards], ignore_index=True)
d = d[d.status == "ok"].copy()
for a, b, name in (("t_decision", "t_scheduled", "dur_schedule_s"), ("t_pull_start", "t_pull_end", "dur_pull_s"),
                   ("t_pull_end", "t_started", "dur_start_s"), ("t_started", "t_ready_observed", "dur_ready_s")):
    d[name] = d[b] - d[a]
out = pathlib.Path("data/startscale_readiness_v5.parquet"); out.parent.mkdir(exist_ok=True)
d.to_parquet(out, index=False); print(len(d), "events ->", out)
