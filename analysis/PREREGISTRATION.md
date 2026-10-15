# Pre-registration: ZoneShift difference-in-differences

**Written:** 2026-10-14, before any treatment-vs-control outcome comparison was run.
**Status at time of writing:** the data pipeline (Phases 1-2) is built. I have seen data-quality
summaries (row counts, exclusion flags, `cbd_congestion_fee` value distribution, zone lists) but
no outcome trends, event-study estimates, or DiD estimates. `analysis/did.py` records the SHA-256
of this file in `results/metrics.json` at run time; any later edit to this file must be listed in
the "Amendments" section below with a reason.

## Question

How did trip volume, fares, speed, and tipping for NYC yellow and green taxi pickups change in
Manhattan Central Business District (CBD) zones after congestion pricing began on 2025-01-05,
relative to comparable non-CBD zones?

## Data

- Source: `marts.agg_zone_day` (built by dbt from NYC TLC yellow + green trip records, clean
  trips only; exclusion rules in `docs/data_quality_report.md`). Records are vendor-submitted and
  not verified by TLC.
- Window: pickups 2024-01-01 to 2025-12-31 (12 months before and 12 months after the policy).
- Main specification uses `service_type = 'all'` (yellow + green combined).

## Units, treatment, control

- **Unit of observation:** pickup taxi zone x calendar day.
- **Treated:** the 38 zones on the MTA Congestion Relief Zone list (`dim_zone.is_cbd`).
- **Control:** all other zones, **excluding**
  - border zones (`dim_zone.is_border_zone`: non-CBD Manhattan zones adjacent to the CBD), because
    of spillover risk;
  - unknown zones 264/265;
  - zones that are not regularly served: a zone is kept only if it has at least one clean trip on
    at least 90% of pre-period days (2024-01-01 to 2025-01-04). This rule uses pre-period activity
    only and is applied to treated and control zones alike. The number of zones dropped by it is
    reported.
- **Post:** `date >= 2025-01-05`.

## Outcomes (primary, 4)

| # | Outcome | Definition | Zone-days used |
|---|---|---|---|
| 1 | Trip volume | ln(1 + trip_count) | Balanced panel: every kept zone x every day; zone-days without trips get trip_count = 0 |
| 2 | Median fare | `median_fare` (metered fare in USD; excludes the CBD fee, surcharges, tolls, tips) | Zone-days with >= 1 trip |
| 3 | Average speed | `avg_speed_mph` (total miles / total hours of the zone-day's trips) | Zone-days with >= 1 trip |
| 4 | Card tip % | `card_tip_pct` (mean of 100 x tip / fare over card trips) | Zone-days with >= 1 card trip |

## Model

Two-way fixed effects difference-in-differences, estimated separately for each outcome:

    y_zt = alpha_z + gamma_t + beta * (CBD_z x Post_t) + e_zt

- alpha_z: zone fixed effects; gamma_t: date fixed effects (one per calendar day).
- Unweighted. Standard errors clustered by zone. Estimated with `linearmodels.PanelOLS`.
- Reported for each outcome: beta, 95% CI, p-value, N (zone-days), number of treated and control
  zones. For outcome 1, also exp(beta) - 1 as an approximate percentage change.
- Multiple outcomes: Holm-Bonferroni adjusted p-values across the 4 primary outcomes are reported
  alongside the unadjusted p-values. Significance level 0.05.
- Results are reported whatever their sign, size, or significance. The specification is not
  changed in response to results.

## Diagnostics

1. **Trend plots:** weekly mean of each outcome for treated vs control zones over the full window.
2. **Event study:** replace CBD x Post with CBD x 1[week = k] for every event week k
   (`dim_date.weeks_from_policy`, week 0 = 2025-01-05..2025-01-11), reference week k = -1,
   same fixed effects and clustering. Plot coefficients with 95% CIs.
3. **Pre-trend test:** joint Wald test that all lead coefficients (k <= -2) equal zero, reported
   with its p-value for each outcome. A rejection is reported as evidence against parallel trends
   and noted next to the main estimate; it does not trigger a change of specification.

## Robustness checks (all reported, including any that disagree with the main result)

1. **Placebo cutoff:** 2024 data only (2024-01-01 to 2024-12-31), fake Post = `date >= 2024-07-01`.
   Expectation under no anticipation/pre-trend: beta close to zero.
2. **Include border zones** in the control group.
3. **Yellow only:** `service_type = 'yellow'`, same zone sample rule applied to yellow trips.
4. **Drop holiday weeks:** exclude event weeks containing a US federal holiday
   (`dim_date.is_holiday_week`).

## Exploratory (labelled as such, not used for the headline)

- **Spillover:** border zones as the "treated" group vs the main control group (CBD zones dropped).

## Known limitations (stated in advance)

- Spillover into control zones (displaced trips) would bias estimates; border-zone exclusion only
  partly addresses this.
- Other changes around January 2025 (e.g. fare or surcharge changes, seasonal shifts that differ
  between Manhattan and other boroughs, ride-hail competition) are not separately identified.
- High-volume for-hire vehicles (Uber/Lyft) are outside the core scope, so substitution between
  taxis and ride-hail is not observed.
- Pickup-zone outcomes do not capture trips that only pass through or end in the CBD.
- Data are vendor-reported and not verified by TLC.

## Amendments

_None._
