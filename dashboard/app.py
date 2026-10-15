"""ZoneShift dashboard: NYC congestion pricing and taxi pickups (Streamlit).

Reads only dashboard/data/ (exported by dashboard/export.py) and results/metrics.json, so it runs
from a fresh clone without the raw data.

Run:
    streamlit run dashboard/app.py
"""
import json
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

DATA = Path(__file__).parent / "data"
METRICS = Path(__file__).resolve().parents[1] / "results" / "metrics.json"
POLICY = pd.Timestamp("2025-01-05")
GROUPS = ["CBD", "Border", "Other"]  # fixed order = fixed colors

st.set_page_config(page_title="ZoneShift", page_icon="🚕", layout="wide")

DARK = st.context.theme.type == "dark"
# Categorical slots 1-3 (dataviz default palette), light/dark steps
GROUP_COLORS = (["#3987e5", "#d95926", "#199e70"] if DARK else ["#2a78d6", "#eb6834", "#1baf7a"])
PERIOD_COLORS = GROUP_COLORS[:2]
NEUTRAL = (56, 56, 53) if DARK else (240, 239, 236)
BLUE_POLE, RED_POLE = (16, 66, 129), (179, 38, 30)

OUTCOME_LABELS = {
    "log_trips": "Trip volume, ln(1 + trips)",
    "median_fare": "Median metered fare (USD)",
    "avg_speed_mph": "Average speed (mph)",
    "card_tip_pct": "Card tip (% of fare)",
}
SPEC_LABELS = {
    "main": "Main (pre-registered)",
    "placebo_2024-07-01": "Placebo cutoff 2024-07-01",
    "include_border_zones": "Include border zones",
    "yellow_only": "Yellow only",
    "drop_holiday_weeks": "Drop holiday weeks",
    "exploratory_spillover_border_vs_control": "Exploratory: border vs control",
}


# ------------------------------------------------------------------ data

@st.cache_data
def load():
    zones = pd.read_parquet(DATA / "dim_zone.parquet")
    zones["zone_group"] = zones.apply(
        lambda r: "CBD" if r.is_cbd else "Border" if r.is_border_zone else "Other", axis=1)
    zones = zones[~zones["is_unknown_zone"]]
    dates = pd.read_parquet(DATA / "dim_date.parquet")
    dates["date_day"] = pd.to_datetime(dates["date_day"])
    day = pd.read_parquet(DATA / "agg_zone_day.parquet")
    day["date_day"] = pd.to_datetime(day["date_day"])
    day = (day.merge(zones[["location_id", "zone_group"]], on="location_id")
              .merge(dates[["date_day", "post_policy", "is_weekend"]], on="date_day"))
    hour = pd.read_parquet(DATA / "agg_zone_hour.parquet")
    hour["month_start"] = pd.to_datetime(hour["month_start"])
    hour = hour.merge(zones[["location_id", "zone_group"]], on="location_id")
    did = pd.read_parquet(DATA / "did_results.parquet")
    es = pd.read_parquet(DATA / "event_study.parquet")
    geo = json.loads((DATA / "zones.geojson").read_text())
    metrics = json.loads(METRICS.read_text())
    return zones, dates, day, hour, did, es, geo, metrics


def summarize(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Exact trip-weighted fare, speed, and card tip % from zone-day rows."""
    d = df.assign(
        fare_x=df["avg_fare"] * df["trip_count"],
        dist_x=df["avg_distance_mi"] * df["trip_count"],
        min_x=df["avg_trip_minutes"] * df["trip_count"],
        tip_x=df["card_tip_pct"].fillna(0) * df["card_trip_count"],
    )
    g = d.groupby(by, observed=True).agg(
        trips=("trip_count", "sum"), fare_x=("fare_x", "sum"), dist_x=("dist_x", "sum"),
        min_x=("min_x", "sum"), tip_x=("tip_x", "sum"), card=("card_trip_count", "sum"),
    ).reset_index()
    g["avg_fare"] = g["fare_x"] / g["trips"]
    g["avg_speed_mph"] = g["dist_x"] / (g["min_x"] / 60)
    g["card_tip_pct"] = g["tip_x"] / g["card"].where(g["card"] > 0)
    return g.drop(columns=["fare_x", "dist_x", "min_x", "tip_x", "card"])


def policy_rule() -> alt.Chart:
    return (alt.Chart(pd.DataFrame({"x": [POLICY]}))
            .mark_rule(strokeDash=[4, 4], strokeWidth=1, color="gray")
            .encode(x="x:T", tooltip=[alt.Tooltip("x:T", title="Congestion pricing start")]))


def lerp(a, b, t):
    return [int(a[i] + (b[i] - a[i]) * t) for i in range(3)]


def caveat(metrics: dict) -> str:
    main = metrics["did_main"]
    fails = sum(r["pretrend_wald_p"] < 0.05 for r in main.values())
    placebo = metrics["did_robustness"]["placebo_2024-07-01"]
    pf = sum(r["p_value"] < 0.05 for r in placebo.values())
    return (f"Pre-registered diagnostics: the parallel-trends test is rejected for {fails} of "
            f"{len(main)} outcomes and the 2024-07-01 placebo is significant for {pf} of "
            f"{len(placebo)}. The difference-in-differences estimates are therefore descriptive "
            "contrasts, not causal effects of congestion pricing.")


zones, dates, day, hour, did, es, geo, metrics = load()

with st.sidebar:
    st.markdown("### ZoneShift")
    service = st.radio("Service", ["all", "yellow", "green"], horizontal=True,
                       help="'all' = yellow + green combined")
    st.caption("NYC TLC trip records 2024-01 to 2025-12, clean trips only. Records are "
               "vendor-reported and not verified by TLC.")

day_s = day[day["service_type"] == service]
hour_s = hour[hour["service_type"] == service]


# ------------------------------------------------------------------ pages

def overview():
    st.title("NYC congestion pricing and taxi pickups")
    st.write("Congestion pricing for Manhattan south of 60th Street (the CBD) began on "
             "2025-01-05. This dashboard compares taxi pickups in CBD zones with border zones just "
             "north of 60th Street and all other zones, before and after that date.")
    m = metrics
    c = st.columns(4)
    c[0].metric("Clean trips", f"{m['fct_trips_rows'] / 1e6:.1f}M",
                help=f"{m['fct_trips_rows']:,} trips")
    c[1].metric("Rows retained", f"{m['dq_pct_retained']:.2f}%")
    c[2].metric("CBD zones (MTA list)", m["cbd_zone_count"])
    c[3].metric("Border zones", m["border_zone_count"])

    st.subheader("Average daily clean pickups, before vs after 2025-01-05")
    st.caption("Descriptive, all services, pooled over trips. Not a causal estimate.")
    desc = m["descriptive_pre_post_by_zone_group"]
    c = st.columns(3)
    for col, (key, label) in zip(c, [("cbd", "CBD zones"), ("border", "Border zones"),
                                     ("other", "All other zones")]):
        d = desc[key]
        col.metric(f"{label}, trips/day after", f"{d['post']['trips_per_day'] / 1e3:,.1f}k",
                   f"{d['trips_per_day_pct_change']:+.1f}% vs {d['pre']['trips_per_day'] / 1e3:,.1f}k before")
    st.warning(caveat(m))


def trends():
    st.title("CBD vs non-CBD trends")
    measures = {"Trips per day": "trips_per_day", "Average fare (USD)": "avg_fare",
                "Average speed (mph)": "avg_speed_mph", "Card tip (% of fare)": "card_tip_pct"}
    label = st.radio("Measure", list(measures), horizontal=True)
    col = measures[label]

    d = day_s.assign(week=day_s["date_day"] - pd.to_timedelta(day_s["date_day"].dt.weekday, unit="D"))
    w = summarize(d, ["week", "zone_group"])
    days_per_week = (dates.assign(week=dates["date_day"] - pd.to_timedelta(dates["date_day"].dt.weekday, unit="D"))
                     .groupby("week").size().rename("n_days"))
    w = w.merge(days_per_week, left_on="week", right_index=True)
    w["trips_per_day"] = w["trips"] / w["n_days"]

    color = alt.Color("zone_group:N", title="Zone group",
                      scale=alt.Scale(domain=GROUPS, range=GROUP_COLORS),
                      legend=alt.Legend(orient="top"))
    base = alt.Chart(w).encode(x=alt.X("week:T", title=None), color=color)
    lines = base.mark_line(strokeWidth=2).encode(
        y=alt.Y(f"{col}:Q", title=label, scale=alt.Scale(zero=col == "trips_per_day")))
    hover = alt.selection_point(fields=["week"], nearest=True, on="pointerover", empty=False)
    points = base.mark_point(size=60, filled=True).encode(
        y=f"{col}:Q", opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("week:T", title="Week of"), alt.Tooltip("zone_group:N", title="Group"),
                 alt.Tooltip(f"{col}:Q", title=label, format=",.2f")],
    ).add_params(hover)
    last = w.sort_values("week").groupby("zone_group").tail(1)
    labels = alt.Chart(last).mark_text(align="left", dx=6, fontSize=11).encode(
        x="week:T", y=f"{col}:Q", text="zone_group:N")
    st.altair_chart((lines + points + labels + policy_rule()).properties(height=420),
                    use_container_width=True)
    st.caption("Weekly values; dashed line = 2025-01-05. Fare, speed, and tip are trip-weighted "
               "(speed = total miles / total hours). Partial weeks at the window edges use their "
               "actual day count.")
    with st.expander("Table view"):
        st.dataframe(w.pivot(index="week", columns="zone_group", values=col).round(2),
                     use_container_width=True)


def zone_map():
    st.title("Zone map")
    options = ["Trips per day, % change (post vs pre)", "Trips per day, before", "Trips per day, after"]
    choice = st.radio("Colour zones by", options, horizontal=True)

    n_pre = int((~dates["post_policy"]).sum())
    n_post = int(dates["post_policy"].sum())
    z = (day_s.groupby(["location_id", "post_policy"])["trip_count"].sum().unstack(fill_value=0)
              .rename(columns={False: "pre", True: "post"}))
    z = z.reindex(zones["location_id"], fill_value=0)
    z["pre_per_day"] = z["pre"] / n_pre
    z["post_per_day"] = z["post"] / n_post
    # % change only for zones with a meaningful base (>= 1 trip/day before)
    z["pct_chg"] = (100 * (z["post_per_day"] / z["pre_per_day"] - 1)).where(z["pre_per_day"] >= 1)
    z = z.join(zones.set_index("location_id")[["zone", "borough", "zone_group"]])

    if choice.startswith("Trips per day, %"):
        vals = z["pct_chg"]
        lim = max(10.0, float(vals.abs().quantile(0.95)))
        def fill(v):
            if pd.isna(v):
                return [200, 200, 200, 60]
            t = min(abs(v) / lim, 1.0)
            return lerp(NEUTRAL, BLUE_POLE if v > 0 else RED_POLE, t) + [210]
        legend = f"Blue = more trips per day after, red = fewer; gray = no change. Scale saturates at ±{lim:.0f}%. Pale gray zones had < 1 trip/day before (no % shown)."
    else:
        vals = z["pre_per_day" if "before" in choice else "post_per_day"]
        top = float(np.log1p(vals).quantile(0.98)) or 1.0
        def fill(v):
            t = min(float(np.log1p(v)) / top, 1.0)
            return lerp((205, 226, 251), (13, 54, 107), t) + [210]
        legend = "Light to dark blue = fewer to more trips per day (log scale)."

    feats = []
    for f in geo["features"]:
        lid = f["properties"]["location_id"]
        if lid not in z.index:
            continue
        r = z.loc[lid]
        props = dict(f["properties"],
                     fill=fill(vals.loc[lid]),
                     group=r.zone_group,
                     pre=f"{r.pre_per_day:,.1f}", post=f"{r.post_per_day:,.1f}",
                     chg="n/a" if pd.isna(r.pct_chg) else f"{r.pct_chg:+.1f}%")
        feats.append(dict(f, properties=props))

    # Per-feature line accessors break Streamlit's deck renderer, so the CBD outline is its own layer
    fills = pdk.Layer(
        "GeoJsonLayer", {"type": "FeatureCollection", "features": feats}, pickable=True,
        stroked=True, filled=True, get_fill_color="properties.fill",
        get_line_color=[120, 120, 120], line_width_min_pixels=1, auto_highlight=True,
    )
    cbd_outline = pdk.Layer(
        "GeoJsonLayer",
        {"type": "FeatureCollection", "features": [f for f in feats if f["properties"]["group"] == "CBD"]},
        stroked=True, filled=False, get_line_color=[255, 255, 255] if DARK else [11, 11, 11],
        line_width_min_pixels=2,
    )
    view = pdk.ViewState(latitude=40.73, longitude=-73.94, zoom=10, pitch=0)
    tooltip = {"html": "<b>{zone}</b> ({borough}, {group})<br/>Trips/day before: {pre}"
                       "<br/>Trips/day after: {post}<br/>Change: {chg}"}
    st.pydeck_chart(pdk.Deck(layers=[fills, cbd_outline], initial_view_state=view, tooltip=tooltip), height=560)
    st.caption(legend + " CBD zones have a thick outline.")
    with st.expander("Table view"):
        st.dataframe(z.reset_index()[["location_id", "zone", "borough", "zone_group", "pre_per_day",
                                      "post_per_day", "pct_chg"]].round(1)
                     .sort_values("post_per_day", ascending=False),
                     use_container_width=True, hide_index=True)


def hours():
    st.title("Hour-of-day patterns")
    c = st.columns(2)
    daytype = c[0].radio("Days", ["Weekdays", "Weekends"], horizontal=True)
    groups = c[1].multiselect("Zone groups", GROUPS, default=["CBD", "Other"])
    weekend = daytype == "Weekends"

    # Month grain: Jan 2025 mixes pre and post days, so it is left out of this comparison
    periods = {"Before (2024)": (pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01")),
               "After (Feb-Dec 2025)": (pd.Timestamp("2025-02-01"), pd.Timestamp("2026-01-01"))}
    frames = []
    for name, (a, b) in periods.items():
        n_days = int(((dates["date_day"] >= a) & (dates["date_day"] < b) & (dates["is_weekend"] == weekend)).sum())
        h = hour_s[(hour_s["month_start"] >= a) & (hour_s["month_start"] < b)
                   & (hour_s["is_weekend"] == weekend) & hour_s["zone_group"].isin(groups)]
        g = h.groupby(["zone_group", "hour_of_day"])["trip_count"].sum().reset_index()
        g["trips_per_day"] = g["trip_count"] / n_days
        g["period"] = name
        frames.append(g)
    d = pd.concat(frames)
    if d.empty:
        st.info("Pick at least one zone group.")
        return
    chart = alt.Chart(d).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=30)).encode(
        x=alt.X("hour_of_day:O", title="Pickup hour"),
        y=alt.Y("trips_per_day:Q", title="Trips per day"),
        color=alt.Color("period:N", title="Period", scale=alt.Scale(domain=list(periods), range=PERIOD_COLORS),
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("zone_group:N", title="Group"), alt.Tooltip("period:N"),
                 alt.Tooltip("hour_of_day:O", title="Hour"),
                 alt.Tooltip("trips_per_day:Q", title="Trips per day", format=",.1f")],
    ).properties(height=320).facet(column=alt.Column("zone_group:N", title=None, sort=GROUPS)) \
     .resolve_scale(y="independent")
    st.altair_chart(chart, use_container_width=True)
    st.caption("Average trips per day picked up in each hour (sum of trips / number of "
               f"{daytype.lower()} in the period). January 2025 is excluded because the monthly "
               "grain mixes days before and after 2025-01-05.")


def causal():
    st.title("Causal analysis results")
    st.warning(caveat(metrics))
    st.markdown("Specification: two-way fixed effects (zone + date), SEs clustered by zone, "
                "pre-registered in `analysis/PREREGISTRATION.md` before any model was run.")

    outcome = st.selectbox("Outcome", list(OUTCOME_LABELS), format_func=OUTCOME_LABELS.get)
    e = es[es["outcome"] == outcome]
    p = did[(did["spec"] == "main") & (did["outcome"] == outcome)]["pretrend_wald_p"].iloc[0]
    band = alt.Chart(e).mark_area(opacity=0.2, color=GROUP_COLORS[0]).encode(
        x=alt.X("week:Q", title="Weeks from 2025-01-05"), y="ci_low:Q", y2="ci_high:Q")
    line = alt.Chart(e).mark_line(strokeWidth=2, color=GROUP_COLORS[0],
                                  point=alt.OverlayMarkDef(size=20)).encode(
        x="week:Q", y=alt.Y("coef:Q", title="Difference vs week -1"),
        tooltip=[alt.Tooltip("week:Q", title="Week"), alt.Tooltip("coef:Q", format=".3f"),
                 alt.Tooltip("ci_low:Q", title="95% CI low", format=".3f"),
                 alt.Tooltip("ci_high:Q", title="95% CI high", format=".3f")])
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="gray").encode(y="y:Q")
    start = alt.Chart(pd.DataFrame({"x": [-0.5]})).mark_rule(strokeDash=[4, 4], color="gray").encode(x="x:Q")
    st.altair_chart((band + line + zero + start).properties(
        height=380, title=f"Event study: {OUTCOME_LABELS[outcome]} (pre-trend joint test p = {p:.3g})"),
        use_container_width=True)

    st.subheader("All specifications")
    t = did.copy()
    t["Specification"] = t["spec"].map(SPEC_LABELS)
    t["Outcome"] = t["outcome"].map(OUTCOME_LABELS)
    t["95% CI"] = t.apply(lambda r: f"[{r.ci_low:.3f}, {r.ci_high:.3f}]", axis=1)
    t["p"] = t["p_value"].map(lambda v: "<0.001" if v < 0.001 else f"{v:.3f}")
    t["p (Holm)"] = t["p_holm"].map(lambda v: "" if pd.isna(v) else "<0.001" if v < 0.001 else f"{v:.3f}")
    st.dataframe(t[["Specification", "Outcome", "coef", "95% CI", "p", "p (Holm)", "n_obs",
                    "n_zones_treated", "n_zones_control"]]
                 .rename(columns={"coef": "Estimate", "n_obs": "N zone-days",
                                  "n_zones_treated": "Treated zones", "n_zones_control": "Control zones"}),
                 use_container_width=True, hide_index=True)


pg = st.navigation([
    st.Page(overview, title="Overview", icon="🏠", default=True),
    st.Page(trends, title="CBD vs non-CBD trends", icon="📈", url_path="trends"),
    st.Page(zone_map, title="Zone map", icon="🗺️", url_path="map"),
    st.Page(hours, title="Hour of day", icon="🕒", url_path="hours"),
    st.Page(causal, title="Causal results", icon="📐", url_path="causal"),
])
pg.run()
