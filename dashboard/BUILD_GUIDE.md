# Dashboard build guide

The Streamlit app (`dashboard/app.py`) is the implemented dashboard. This guide documents the
data model and measures so the same dashboard can be rebuilt in Tableau Public or Power BI.

## Files (`dashboard/data/`, written by `python dashboard/export.py [--csv]`)

| File | Grain | Role |
|---|---|---|
| `agg_zone_day` | pickup zone x day x service_type | Fact |
| `agg_zone_hour` | pickup zone x month x hour x weekend flag x service_type | Fact |
| `dim_zone` | taxi zone | Dimension |
| `dim_date` | calendar day | Dimension |
| `did_results` | specification x outcome | Standalone (causal results) |
| `event_study` | outcome x week from policy | Standalone (causal results) |
| `zones.geojson` | taxi zone polygon (WGS84) | Map shapes, joined on `location_id` |

## Star schema relationships

```
dim_zone.location_id  1 ──< *  agg_zone_day.location_id
dim_date.date_day     1 ──< *  agg_zone_day.date_day
dim_zone.location_id  1 ──< *  agg_zone_hour.location_id
zones.geojson.location_id 1 ── 1 dim_zone.location_id
```

`agg_zone_hour.month_start` matches `dim_date.month_start`, but that is many-to-many; use it as a
plain attribute (or relate through a separate month table) rather than a relationship.

**Important: `service_type` contains `yellow`, `green`, and `all` (= yellow + green).** Every
visual must filter to one value (default `all`), otherwise trips are double counted. In Power BI,
make it a single-select slicer with `all` as the default; in Tableau, a single-value filter.

## Measures

Medians and averages cannot be summed across rows. The measures below rebuild exact
trip-weighted values from the stored columns.

| Measure | Definition |
|---|---|
| Trips | sum(trip_count) |
| Trips per day | Trips / number of days in the filter context |
| Average fare | sum(avg_fare x trip_count) / Trips |
| Average speed (mph) | sum(avg_distance_mi x trip_count) / (sum(avg_trip_minutes x trip_count) / 60) |
| Card tip % | sum(card_tip_pct x card_trip_count) / sum(card_trip_count) |
| CBD fee collected | sum(total_cbd_fee) |
| Trips per day % change | (Trips per day, post) / (Trips per day, pre) - 1, split on dim_date.post_policy |

### Power BI (DAX)

```DAX
Trips = SUM ( agg_zone_day[trip_count] )

Days = COUNTROWS ( dim_date )

Trips per Day = DIVIDE ( [Trips], [Days] )

Average Fare =
DIVIDE ( SUMX ( agg_zone_day, agg_zone_day[avg_fare] * agg_zone_day[trip_count] ), [Trips] )

Average Speed (mph) =
DIVIDE (
    SUMX ( agg_zone_day, agg_zone_day[avg_distance_mi] * agg_zone_day[trip_count] ),
    SUMX ( agg_zone_day, agg_zone_day[avg_trip_minutes] * agg_zone_day[trip_count] ) / 60
)

Card Tip % =
DIVIDE (
    SUMX ( agg_zone_day, agg_zone_day[card_tip_pct] * agg_zone_day[card_trip_count] ),
    SUM ( agg_zone_day[card_trip_count] )
)

Trips per Day Pre = CALCULATE ( [Trips per Day], dim_date[post_policy] = FALSE () )
Trips per Day Post = CALCULATE ( [Trips per Day], dim_date[post_policy] = TRUE () )
Trips per Day % Change = DIVIDE ( [Trips per Day Post], [Trips per Day Pre] ) - 1
```

Zone group (calculated column on `dim_zone`):

```DAX
Zone Group = IF ( dim_zone[is_cbd], "CBD", IF ( dim_zone[is_border_zone], "Border", "Other" ) )
```

### Tableau (calculated fields)

```
Zone Group:      IF [Is Cbd] THEN "CBD" ELSEIF [Is Border Zone] THEN "Border" ELSE "Other" END
Average Fare:    SUM([Avg Fare] * [Trip Count]) / SUM([Trip Count])
Average Speed:   SUM([Avg Distance Mi] * [Trip Count]) / (SUM([Avg Trip Minutes] * [Trip Count]) / 60)
Card Tip %:      SUM([Card Tip Pct] * [Card Trip Count]) / SUM([Card Trip Count])
Trips per Day:   SUM([Trip Count]) / COUNTD([Date Day])
```

## Pages

1. **Overview KPIs:** clean trips, % retained after data-quality rules, CBD zones, daily CBD
   trips pre vs post (descriptive), and the headline caveat that the pre-trend diagnostics fail.
2. **CBD vs non-CBD trends:** weekly Trips per day / Average fare / Average speed / Card tip % by
   Zone Group, with a reference line at 2025-01-05 and a service_type filter.
3. **Zone map:** zones.geojson filled by Trips per day % change (diverging, gray at 0), CBD
   outlined; tooltip with zone, borough, pre and post values.
4. **Hour-of-day patterns:** from `agg_zone_hour`, trips per day by hour, pre vs post, split
   weekday/weekend and Zone Group. Divide by the number of days of that type in each period.
5. **Causal results:** `did_results` table (main + robustness, with CIs and p-values) and the
   `event_study` chart (coefficient line with CI band, reference week -1), with the
   pre-registration link and the parallel-trends caveat shown next to the estimates.

All values come from the exported files; nothing is typed into the dashboard by hand.
