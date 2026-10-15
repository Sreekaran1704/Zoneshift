{#
  Pickup zone x day x service_type, plus service_type = 'all' rows (yellow + green combined)
  so medians are computed on the combined trips rather than re-aggregated.
  Sparse: zone-days with zero clean trips have no row.
#}
select
    pu_location_id                                                  as location_id,
    pickup_date                                                     as date_day,
    coalesce(service_type, 'all')                                   as service_type,
    count(*)                                                        as trip_count,
    median(fare_amount)                                             as median_fare,
    avg(fare_amount)                                                as avg_fare,
    sum(trip_distance_mi) / nullif(sum(trip_minutes) / 60.0, 0)     as avg_speed_mph,
    avg(tip_pct)                                                    as card_tip_pct,
    count(tip_pct)                                                  as card_trip_count,
    avg(trip_distance_mi)                                           as avg_distance_mi,
    avg(trip_minutes)                                               as avg_trip_minutes,
    avg(case when dropoff_in_cbd then 1.0 else 0.0 end)             as dropoff_cbd_share,
    sum(coalesce(cbd_congestion_fee, 0))                            as total_cbd_fee,
    sum(total_amount)                                               as total_amount
from {{ ref('fct_trips') }}
group by grouping sets (
    (pu_location_id, pickup_date, service_type),
    (pu_location_id, pickup_date)
)
