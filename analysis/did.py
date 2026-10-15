"""Difference-in-differences analysis of NYC congestion pricing on taxi pickups.

Implements analysis/PREREGISTRATION.md exactly: TWFE DiD (zone + date FE, SEs clustered by zone)
for four outcomes, a weekly event study with a joint pre-trend test, the four pre-registered
robustness checks, and the exploratory border-zone spillover comparison.

Outputs: results/did_results.csv, results/event_study.csv, analysis/figures/*.png, and
headline numbers in results/metrics.json.

Usage:
    python analysis/did.py
"""
import hashlib
import sys
import warnings
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from linearmodels.panel import PanelOLS  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingestion"))
from utils import DB_PATH, RESULTS_DIR, update_metrics  # noqa: E402

PREREG = ROOT / "analysis" / "PREREGISTRATION.md"
FIG_DIR = ROOT / "analysis" / "figures"

POLICY = pd.Timestamp("2025-01-05")
PLACEBO_CUTOFF = pd.Timestamp("2024-07-01")
PLACEBO_END = pd.Timestamp("2025-01-01")  # exclusive: 2024 data only
ACTIVITY_SHARE = 0.90                    # min share of pre-period days with >= 1 trip
REF_WEEK = -1

OUTCOMES = {
    "log_trips": "Trip volume, ln(1 + trips)",
    "median_fare": "Median metered fare (USD)",
    "avg_speed_mph": "Average speed (mph)",
    "card_tip_pct": "Card tip (% of fare)",
}

# Chart tokens (dataviz skill default palette, light mode)
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
C_TREATED, C_CONTROL = "#2a78d6", "#eb6834"  # categorical slots 1, 2


# ---------------------------------------------------------------- data

def load_panel(con: duckdb.DuckDBPyConnection, service_type: str) -> tuple[pd.DataFrame, set]:
    """Balanced zone x day panel for one service_type, plus the set of regularly served zones."""
    zones = con.sql("""
        select location_id, is_cbd, is_border_zone, is_unknown_zone from marts.dim_zone
    """).df()
    dates = con.sql("""
        select date_day, weeks_from_policy, is_holiday_week from marts.dim_date
    """).df()
    agg = con.execute("""
        select location_id, date_day, trip_count, median_fare, avg_speed_mph, card_tip_pct
        from marts.agg_zone_day where service_type = ?
    """, [service_type]).df()
    for df in (dates, agg):
        df["date_day"] = pd.to_datetime(df["date_day"])

    # Pre-registered sample rule: >= 1 clean trip on >= 90% of pre-period days
    n_pre_days = (dates["date_day"] < POLICY).sum()
    pre_days = agg[agg["date_day"] < POLICY].groupby("location_id")["date_day"].nunique()
    regular = set(pre_days[pre_days >= ACTIVITY_SHARE * n_pre_days].index)

    panel = zones.merge(dates, how="cross").merge(agg, on=["location_id", "date_day"], how="left")
    panel["trip_count"] = panel["trip_count"].fillna(0)
    panel["log_trips"] = np.log1p(panel["trip_count"])
    for c in ["is_cbd", "is_border_zone", "is_unknown_zone", "is_holiday_week"]:
        panel[c] = panel[c].astype(bool)
    panel["post"] = panel["date_day"] >= POLICY
    return panel, regular


def select_sample(panel: pd.DataFrame, regular: set, treated: str = "cbd",
                  include_border: bool = False) -> pd.DataFrame:
    base = panel[~panel["is_unknown_zone"] & panel["location_id"].isin(regular)]
    if treated == "cbd":
        keep = base["is_cbd"] | include_border | ~base["is_border_zone"]
        return base[keep].assign(treated=base["is_cbd"])
    if treated == "border":  # exploratory spillover: border zones vs main control, CBD dropped
        return base[~base["is_cbd"]].assign(treated=base["is_border_zone"])
    raise ValueError(treated)


# ---------------------------------------------------------------- models

def fit(d: pd.DataFrame, outcome: str, X: pd.DataFrame):
    y = d[outcome]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return PanelOLS(y, X, entity_effects=True, time_effects=True).fit(
            cov_type="clustered", cluster_entity=True)


def did(df: pd.DataFrame, outcome: str, post_col: str = "post") -> dict:
    d = df.dropna(subset=[outcome]).set_index(["location_id", "date_day"])
    X = (d["treated"] & d[post_col]).astype(float).to_frame("treat_post")
    res = fit(d, outcome, X)
    ci = res.conf_int().loc["treat_post"]
    pre = d[~d[post_col]]
    beta = float(res.params["treat_post"])
    return {
        "outcome": outcome,
        "coef": beta,
        "se": float(res.std_errors["treat_post"]),
        "ci_low": float(ci["lower"]),
        "ci_high": float(ci["upper"]),
        "p_value": float(res.pvalues["treat_post"]),
        "pct_change": float(np.expm1(beta) * 100) if outcome == "log_trips" else np.nan,
        "n_obs": int(res.nobs),
        "n_zones_treated": int(d.loc[d["treated"]].index.get_level_values(0).nunique()),
        "n_zones_control": int(d.loc[~d["treated"]].index.get_level_values(0).nunique()),
        "treated_pre_mean": float(pre.loc[pre["treated"], outcome].mean()),
        "control_pre_mean": float(pre.loc[~pre["treated"], outcome].mean()),
    }


def event_study(df: pd.DataFrame, outcome: str) -> tuple[pd.DataFrame, dict]:
    d = df.dropna(subset=[outcome]).set_index(["location_id", "date_day"])
    weeks = sorted(w for w in d["weeks_from_policy"].unique() if w != REF_WEEK)
    X = pd.DataFrame({f"w{w}": (d["treated"] & (d["weeks_from_policy"] == w)).astype(float)
                      for w in weeks}, index=d.index)
    res = fit(d, outcome, X)
    ci = res.conf_int()
    coefs = pd.DataFrame({
        "outcome": outcome, "week": weeks,
        "coef": [res.params[f"w{w}"] for w in weeks],
        "ci_low": [ci.loc[f"w{w}", "lower"] for w in weeks],
        "ci_high": [ci.loc[f"w{w}", "upper"] for w in weeks],
    })
    coefs = pd.concat([coefs, pd.DataFrame([{"outcome": outcome, "week": REF_WEEK,
                                             "coef": 0.0, "ci_low": 0.0, "ci_high": 0.0}])])
    leads = [f"w{w}" for w in weeks if w <= -2]
    R = np.zeros((len(leads), X.shape[1]))
    for i, c in enumerate(leads):
        R[i, X.columns.get_loc(c)] = 1.0
    wt = res.wald_test(restriction=R, value=np.zeros(len(leads)))
    test = {"pretrend_wald_stat": float(wt.stat), "pretrend_wald_df": int(wt.df),
            "pretrend_wald_p": float(wt.pval), "n_leads": len(leads)}
    return coefs.sort_values("week").reset_index(drop=True), test


# ---------------------------------------------------------------- figures

def style_axes(ax, title: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=10, color=INK, pad=8)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(INK_2)
    ax.tick_params(colors=INK_2, labelsize=8, length=0)


def new_figure(suptitle: str):
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), facecolor=SURFACE)
    fig.suptitle(suptitle, x=0.01, ha="left", fontsize=12, color=INK)
    return fig, axes.ravel()


def plot_trends(df: pd.DataFrame, path: Path) -> None:
    fig, axes = new_figure("Weekly mean by group: CBD zones vs control zones (border zones excluded)")
    for ax, (outcome, label) in zip(axes, OUTCOMES.items()):
        w = (df.dropna(subset=[outcome])
               .groupby(["weeks_from_policy", "treated"])[outcome].mean().unstack())
        x = POLICY + pd.to_timedelta(w.index * 7, unit="D")
        for flag, color, name in [(True, C_TREATED, "CBD"), (False, C_CONTROL, "Control")]:
            ax.plot(x, w[flag], color=color, linewidth=2, label=name)
            ax.annotate(name, (x[-1], w[flag].iloc[-1]), xytext=(4, 0), textcoords="offset points",
                        va="center", fontsize=8, color=INK_2)
        ax.axvline(POLICY, color=INK_2, linewidth=1, linestyle="--")
        style_axes(ax, label)
    axes[0].legend(frameon=False, fontsize=8, loc="upper left", labelcolor=INK_2)
    fig.text(0.01, 0.01, "Dashed line: congestion pricing start (2025-01-05). Source: NYC TLC trip "
             "records (vendor-reported), clean trips only.", fontsize=8, color=INK_2)
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def plot_event_study(es: pd.DataFrame, tests: dict, path: Path) -> None:
    fig, axes = new_figure("Event study: CBD vs control by week relative to 2025-01-05 (ref. week -1)")
    for ax, (outcome, label) in zip(axes, OUTCOMES.items()):
        e = es[es["outcome"] == outcome]
        ax.fill_between(e["week"], e["ci_low"], e["ci_high"], color=C_TREATED, alpha=0.18, linewidth=0)
        ax.plot(e["week"], e["coef"], color=C_TREATED, linewidth=2)
        ax.axhline(0, color=INK_2, linewidth=1)
        ax.axvline(-0.5, color=INK_2, linewidth=1, linestyle="--")
        p = tests[outcome]["pretrend_wald_p"]
        style_axes(ax, f"{label}\npre-trend joint test p = {p:.3g}")
        ax.set_xlabel("Weeks from policy start", fontsize=8, color=INK_2)
    fig.text(0.01, 0.01, "Line: estimated difference vs week -1; band: 95% CI (SEs clustered by zone). "
             "Zone and date fixed effects.", fontsize=8, color=INK_2)
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


# ---------------------------------------------------------------- main

def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    prereg_sha = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    con = duckdb.connect(str(DB_PATH), read_only=True)

    panel_all, regular_all = load_panel(con, "all")
    panel_yel, regular_yel = load_panel(con, "yellow")
    main_df = select_sample(panel_all, regular_all)

    eligible = panel_all[~panel_all["is_unknown_zone"]].drop_duplicates("location_id")
    dropped = eligible[~eligible["location_id"].isin(regular_all)]
    sample_info = {
        "zones_treated": int(main_df.loc[main_df["treated"], "location_id"].nunique()),
        "zones_control": int(main_df.loc[~main_df["treated"], "location_id"].nunique()),
        "zones_dropped_activity_rule_cbd": int(dropped["is_cbd"].sum()),
        "zones_dropped_activity_rule_noncbd": int((~dropped["is_cbd"]).sum()),
        "days": int(main_df["date_day"].nunique()),
    }
    print("Sample:", sample_info)

    # Main DiD + event studies
    rows, es_frames, pretests = [], [], {}
    for outcome in OUTCOMES:
        rows.append({"spec": "main", **did(main_df, outcome)})
        es, test = event_study(main_df, outcome)
        es_frames.append(es)
        pretests[outcome] = test
        rows[-1].update(test)
    main_p = [r["p_value"] for r in rows]
    for r, p_holm in zip(rows, multipletests(main_p, method="holm")[1]):
        r["p_holm"] = float(p_holm)

    # Robustness (pre-registered) + exploratory
    placebo_df = main_df[main_df["date_day"] < PLACEBO_END].assign(
        placebo_post=lambda d: d["date_day"] >= PLACEBO_CUTOFF)
    specs = {
        "placebo_2024-07-01": (placebo_df, "placebo_post"),
        "include_border_zones": (select_sample(panel_all, regular_all, include_border=True), "post"),
        "yellow_only": (select_sample(panel_yel, regular_yel), "post"),
        "drop_holiday_weeks": (main_df[~main_df["is_holiday_week"]], "post"),
        "exploratory_spillover_border_vs_control": (select_sample(panel_all, regular_all, "border"), "post"),
    }
    for name, (df, post_col) in specs.items():
        for outcome in OUTCOMES:
            rows.append({"spec": name, **did(df, outcome, post_col)})

    results = pd.DataFrame(rows)
    cols = ["spec", "outcome", "coef", "se", "ci_low", "ci_high", "p_value", "p_holm", "pct_change",
            "n_obs", "n_zones_treated", "n_zones_control", "treated_pre_mean", "control_pre_mean",
            "pretrend_wald_stat", "pretrend_wald_df", "pretrend_wald_p", "n_leads"]
    results = results.reindex(columns=cols)
    results.to_csv(RESULTS_DIR / "did_results.csv", index=False, float_format="%.6g")
    es_all = pd.concat(es_frames)
    es_all.to_csv(RESULTS_DIR / "event_study.csv", index=False, float_format="%.6g")

    plot_trends(main_df, FIG_DIR / "trends_cbd_vs_control.png")
    plot_event_study(es_all, pretests, FIG_DIR / "event_study.png")

    r6 = lambda v: None if pd.isna(v) else round(float(v), 6)  # noqa: E731
    main_metrics = {
        r["outcome"]: {k: r6(r[k]) for k in ["coef", "ci_low", "ci_high", "p_value", "p_holm",
                                             "pct_change", "pretrend_wald_p", "treated_pre_mean"]}
                      | {"n_obs": int(r["n_obs"])}
        for r in rows if r["spec"] == "main"
    }
    robustness = {
        spec: {r["outcome"]: {"coef": r6(r["coef"]), "p_value": r6(r["p_value"])}
               for _, r in g.iterrows()}
        for spec, g in results[results["spec"] != "main"].groupby("spec")
    }
    update_metrics({
        "analysis_prereg_sha256": prereg_sha,
        "analysis_sample": sample_info,
        "did_main": main_metrics,
        "did_robustness": robustness,
    })

    show = results[["spec", "outcome", "coef", "ci_low", "ci_high", "p_value", "n_obs"]]
    with pd.option_context("display.width", 140, "display.float_format", "{:.4g}".format):
        print(show.to_string(index=False))
    print("Pre-trend joint test p:", {k: round(v["pretrend_wald_p"], 4) for k, v in pretests.items()})


if __name__ == "__main__":
    main()
