# Building the ZoneShift dashboard in Tableau Public

A step-by-step guide to rebuild the Streamlit dashboard as a Tableau Public workbook (free, works
on Mac). The data model and measures match [`dashboard/BUILD_GUIDE.md`](../dashboard/BUILD_GUIDE.md).

## 0. Before you start

1. Install **Tableau Public** (desktop app) from https://public.tableau.com/app/discover and
   create a free Tableau Public account. Everything you publish there is **public**; the
   data here is public TLC data, so that is fine.
2. Export the data as CSV (Tableau Public does not read Parquet):

   ```bash
   .venv/bin/python dashboard/export.py --csv
   ```

   This writes `dashboard/data/*.csv` (gitignored) next to the Parquet files, plus
   `zones.geojson` for the map.

## 1. Data sources

Create **two** data sources (Data > New Data Source > Text file):

**A. `ZoneShift daily`** (main model, uses Tableau *relationships*, the noodle icon, not joins):

| Logical table | File | Relate to | On |
|---|---|---|---|
| `agg_zone_day` (base) | `agg_zone_day.csv` | | |
| `dim_zone` | `dim_zone.csv` | `agg_zone_day` | `Location Id = Location Id` |
| `dim_date` | `dim_date.csv` | `agg_zone_day` | `Date Day = Date Day` |
| `zones` | `zones.geojson` (Spatial file) | `dim_zone` | `Location Id = Location Id` |

Check data types in the data grid: `Location Id` = Number (whole), `Date Day` = Date, `Is Cbd`,
`Is Border Zone`, `Post Policy`, `Is Weekend` = Boolean.

**B. `ZoneShift hourly`**: `agg_zone_hour.csv` related to `dim_zone.csv` on `Location Id`.
Set `Month Start` to Date.

**C. `Causal results`**: `did_results.csv` and, as a separate data source, `event_study.csv`.

> **Important:** `service_type` is `yellow`, `green` or `all` (= both). Add **Service Type** as a
> filter on every sheet, set to **Single Value (list)** with default `all`, and apply it to all
> sheets that use the same data source (right-click the filter > Apply to Worksheets > All Using
> This Data Source). Otherwise trips are counted twice.

## 2. Calculated fields

Create these in data source A (Analysis > Create Calculated Field):

```
Zone Group      IF [Is Cbd] THEN "CBD" ELSEIF [Is Border Zone] THEN "Border" ELSE "Other" END
Trips           SUM([Trip Count])
Trips per Day   SUM([Trip Count]) / COUNTD([Date Day])
Average Fare    SUM([Avg Fare] * [Trip Count]) / SUM([Trip Count])
Average Speed   SUM([Avg Distance Mi] * [Trip Count]) / (SUM([Avg Trip Minutes] * [Trip Count]) / 60)
Card Tip %      SUM([Card Tip Pct] * [Card Trip Count]) / SUM([Card Trip Count])
Period          IF [Post Policy] THEN "After 2025-01-05" ELSE "Before" END
Trips/Day Pre   SUM(IF NOT [Post Policy] THEN [Trip Count] END) / COUNTD(IF NOT [Post Policy] THEN [Date Day] END)
Trips/Day Post  SUM(IF [Post Policy] THEN [Trip Count] END) / COUNTD(IF [Post Policy] THEN [Date Day] END)
Pct Change      [Trips/Day Post] / [Trips/Day Pre] - 1
```

Format `Pct Change` and `Card Tip %` as percentages (Card Tip % is already 0-100, so use number
with 1 decimal and a `%` suffix; Pct Change is a ratio, so use Percentage).

`COUNTD([Date Day])` counts only days that have rows in the current view. For a whole zone group
that is every day; for a single low-volume zone it can skip zero-trip days. The Streamlit app uses
calendar days, so expect small differences for tiny zones.

## 3. Sheets

Use the same colors as the Streamlit app so the two dashboards read alike:
CBD `#2a78d6` (blue), Border `#eb6834` (orange), Other `#1baf7a` (aqua); Before `#2a78d6`,
After `#eb6834`. Set them once: right-click Zone Group in the Color legend > Edit Colors.

1. **KPIs** (BANs): four sheets, each one number in large text: `Trips` (all clean trips),
   `Trips/Day Pre` and `Trips/Day Post` with Zone Group = CBD, and `Pct Change` for CBD.
2. **Weekly trends**: Columns `WEEK(Date Day)` (continuous, Exact Date > Week Number or
   "Week" truncation); Rows a parameter-driven measure (create a parameter *Measure* with values
   Trips per Day / Average Fare / Average Speed / Card Tip %, and a calc
   `CASE [Measure] WHEN "Trips per Day" THEN [Trips per Day] ... END`); Color `Zone Group`.
   Add a reference line: Analytics pane > Reference Line > Constant `#2025-01-05#`, label
   "Congestion pricing start". Tooltip: week, group, value.
3. **Zone map**: double-click `Geometry` (from zones.geojson) to draw polygons; Detail
   `Location Id`, `Zone`; Color `Pct Change` with a **diverging** palette (Red-Blue Diverging,
   centered at 0, reversed so blue = increase). Exclude zones with `Trips/Day Pre` < 1 (filter on a
   calc `[Trips/Day Pre] >= 1`). Add a second map layer filtered to Zone Group = CBD with only a
   dark border (Color > Border) to outline the CBD.
4. **Hour of day** (data source B): Columns `Hour Of Day` (discrete), Rows `SUM(Trip Count)`
   divided by the number of days, Color a calc `IF YEAR([Month Start]) = 2024 THEN "Before (2024)"
   ELSEIF [Month Start] >= #2025-02-01# THEN "After (Feb-Dec 2025)" END` (exclude NULL, which drops
   Jan 2025 because it mixes pre and post days); filter `Is Weekend`; Columns also `Zone Group`
   for small multiples.
5. **Causal results** (data source C): a text table of `did_results` with Spec, Outcome, Coef,
   Ci Low, Ci High, P Value, N Obs (filter Spec = main for the headline view); and an event-study
   chart from `event_study`: Columns `Week`, Rows `Coef` as a line plus `Ci Low`/`Ci High` as an
   area band (Measure Names/Values on a dual axis, synchronized), filter `Outcome`, reference
   line at 0 and at -0.5.

## 4. Dashboard

1. New Dashboard, size **Automatic** (or 1200 x 900).
2. Layout: title row ("NYC congestion pricing and taxi pickups"), KPI row, then trends (full
   width), then map and hour-of-day side by side, then causal results.
3. Add a **text box** under the title with the caveat, copied from the README's *What this does and
   does not show* section: the pre-registered diagnostics reject parallel trends, so the DiD
   estimates are descriptive contrasts, not causal effects. Also add "Source: NYC TLC trip
   records (vendor-reported, not verified by TLC)".
4. Use the Service Type filter as a dashboard filter applied to all A/B sheets.
5. Turn the map into a filter: select the map > Use as Filter, so clicking a zone filters the
   trends.

## 5. Publish

File > Save to Tableau Public As... > sign in > name it **ZoneShift**. After it uploads, open
the workbook page, check **Show Viz on profile**, and copy the link into the README and your
resume. To update later, re-export the CSVs, open the workbook, Data > Refresh All Extracts, and
save to Tableau Public again under the same name.
