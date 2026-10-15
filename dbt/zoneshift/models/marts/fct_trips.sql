{#
  Clean trips only (is_excluded = false). Incremental by source file: each run appends trips from
  monthly files not yet loaded. Use --full-refresh if TLC republishes an existing month.
#}
{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail'
    )
}}

select
    trip_id,
    service_type,
    vendor_id,
    pickup_at,
    dropoff_at,
    cast(pickup_at as date)  as pickup_date,
    hour(pickup_at)          as pickup_hour,
    pu_location_id,
    do_location_id,
    pickup_in_cbd,
    dropoff_in_cbd,
    passenger_count,
    trip_distance_mi,
    trip_minutes,
    avg_mph,
    ratecode_id,
    payment_type,
    fare_amount,
    extra,
    mta_tax,
    tip_amount,
    tip_pct,
    tolls_amount,
    improvement_surcharge,
    congestion_surcharge,
    airport_fee,
    cbd_congestion_fee,
    ehail_fee,
    total_amount,
    trip_type,
    source_file,
    source_month
from {{ ref('int_trips_cleaned') }}
where not is_excluded
{% if is_incremental() %}
  and source_file not in (select distinct source_file from {{ this }})
{% endif %}
