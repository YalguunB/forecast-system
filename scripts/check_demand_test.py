"""Эрэлтийн шалгалт: 2025 оны таамаглалыг (өгөгдөл ≤ 2024-12) ЖИНХЭНЭ эрэлт ба бодит борлуулалттай харьцуулна.
Системийн кодыг ашиглахгүй (зөвхөн pandas + SQL). Хэрэглээ:
  python scripts/check_demand_test.py <gen_demand_test.py-ийн --out хавтас> <sales туршилтын id> <demand туршилтын id> <шошго>"""
import json, os, sys
import pandas as pd, psycopg
P, e_sales, e_dem, tag = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
t = pd.read_csv(f"{P}/true_demand.csv", parse_dates=["date"])
t = t[t.date.dt.year == 2025]; t["m"] = t.date.dt.to_period("M").dt.to_timestamp()
truth = t.groupby(["product_id", "m"]).agg(demand=("true_demand", "sum"), sales=("sales", "sum")).reset_index()
pol = t.groupby("product_id").policy.first()
def live(conn, eid):
    cur = conn.execute("""SELECT s.product_id, fv.target_date, fv.y_hat FROM experiment.model_selection ms
        JOIN experiment.run sr ON sr.run_id=ms.run_id
        JOIN experiment.run r ON r.experiment_id=ms.experiment_id AND r.model=sr.model AND r.params=sr.params
        JOIN forecast.forecast_value fv ON fv.run_id=r.run_id AND fv.series_id=ms.series_id AND fv.split='live'
        JOIN curated.series s ON s.id=ms.series_id WHERE ms.experiment_id=%s AND ms.horizon=12""", (eid,))
    d = pd.DataFrame(cur.fetchall(), columns=["product_id", "m", "f"]); d["m"] = pd.to_datetime(d["m"]); return d
with psycopg.connect(os.environ.get("CHECK_DSN", "postgresql://fc_owner:owner@localhost:5432/forecast")) as conn:
    fs, fd = live(conn, e_sales).rename(columns={"f": "fc_sales"}), live(conn, e_dem).rename(columns={"f": "fc_demand"})
df = truth.merge(fs, on=["product_id", "m"]).merge(fd, on=["product_id", "m"]); df["policy"] = df.product_id.map(pol)
df.to_csv(f"{P}/{tag}_detail.csv", index=False)
yr = df.groupby(["policy", "product_id"])[["demand", "sales", "fc_sales", "fc_demand"]].sum().reset_index()
out = {}
for p, g in yr.groupby("policy"):
    r = {}
    for col in ("fc_sales", "fc_demand"):
        e = (g[col] - g["demand"]) / g["demand"]
        r[col] = {"total_vs_true_demand": round(float(g[col].sum() / g["demand"].sum() - 1), 4),
                  "median_abs_err_vs_demand": round(float(e.abs().median()), 4),
                  "median_bias_vs_demand": round(float(e.median()), 4)}
    r["actual_sales_vs_demand"] = round(float(g["sales"].sum() / g["demand"].sum() - 1), 4)
    r["totals"] = {k: round(float(g[k].sum())) for k in ("demand", "sales", "fc_sales", "fc_demand")}
    out[p] = r
mon = df.groupby("m")[["demand", "sales", "fc_sales", "fc_demand"]].sum()
monp = df[df.policy == "tight"].groupby("m")[["demand", "sales", "fc_sales", "fc_demand"]].sum()
monp.round(0).to_csv(f"{P}/{tag}_monthly_tight.csv")
print(json.dumps(out, ensure_ascii=False, indent=1)); print(monp.round(0).to_string())
