{#
  Hour-of-day profile: pickup zone x month x hour x weekday/weekend x service_type (+ 'all').
  Monthly grain keeps it small enough for BI tools while still splitting pre/post policy.
#}
select
    t.pu_location_id                                                as location_id,
    d.month_start,
    t.pickup_hour                                                   as hour_of_day,
    d.is_weekend,
    coalesce(t.service_type, 'all')                                 as service_type,
    count(*)                                                        as trip_count,
    count(distinct t.pickup_date)                                   as active_days,
    median(t.fare_amount)                                           as median_fare,
    sum(t.trip_distance_mi) / nullif(sum(t.trip_minutes) / 60.0, 0) as avg_speed_mph,
    avg(t.tip_pct)                                                  as card_tip_pct
from {{ ref('fct_trips') }} as t
join {{ ref('dim_date') }} as d on t.pickup_date = d.date_day
group by grouping sets (
    (t.pu_location_id, d.month_start, t.pickup_hour, d.is_weekend, t.service_type),
    (t.pu_location_id, d.month_start, t.pickup_hour, d.is_weekend)
)
