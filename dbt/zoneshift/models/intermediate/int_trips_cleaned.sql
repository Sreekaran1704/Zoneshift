{#
  All trips with derived measures, CBD treatment flags, and one boolean per exclusion rule.
  Nothing is dropped here; fct_trips keeps rows where is_excluded = false.
#}
with trips as (
    select * from {{ ref('int_trips_unioned') }}
),

cbd as (
    select location_id from {{ ref('stg_cbd_zones') }}
),

derived as (
    select
        trips.*,
        date_diff('second', pickup_at, dropoff_at) / 60.0 as trip_minutes,
        pu_cbd.location_id is not null                    as pickup_in_cbd,
        do_cbd.location_id is not null                    as dropoff_in_cbd
    from trips
    left join cbd as pu_cbd on trips.pu_location_id = pu_cbd.location_id
    left join cbd as do_cbd on trips.do_location_id = do_cbd.location_id
),

flagged as (
    select
        *,
        case when trip_minutes > 0 then trip_distance_mi / (trip_minutes / 60.0) end as avg_mph,
        -- Tip as % of the metered fare; card only because cash tips are not recorded
        case when payment_type = 1 and fare_amount > 0
             then 100.0 * tip_amount / fare_amount end                               as tip_pct,

        coalesce(trip_distance_mi <= 0, true)                                       as flag_nonpositive_distance,
        coalesce(fare_amount < 0, false)                                            as flag_negative_fare,
        coalesce(dropoff_at < pickup_at, true)                                      as flag_dropoff_before_pickup,
        coalesce(trip_minutes > 180, false)                                         as flag_over_3_hours,
        -- distance > 80 mph * hours; also catches zero-duration trips with positive distance
        coalesce(trip_distance_mi > 80 * trip_minutes / 60.0, false)                as flag_over_80_mph,
        coalesce(pickup_at < timestamp '{{ var("analysis_start") }}'
              or pickup_at >= timestamp '{{ var("analysis_end") }}', true)          as flag_outside_window,
        coalesce(pu_location_id in (264, 265) or do_location_id in (264, 265), true) as flag_unknown_zone
    from derived
)

select
    *,
    (flag_nonpositive_distance or flag_negative_fare or flag_dropoff_before_pickup
     or flag_over_3_hours or flag_over_80_mph or flag_outside_window or flag_unknown_zone) as is_excluded
from flagged
