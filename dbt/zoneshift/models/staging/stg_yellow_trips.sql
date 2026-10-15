with source as (
    select * from {{ source('raw', 'yellow_tripdata') }}
)

select
    {{ trip_id(1, 'filename', 'file_row_number') }}  as trip_id,
    'yellow'                                         as service_type,
    cast(vendorid as integer)                        as vendor_id,
    cast(tpep_pickup_datetime as timestamp)          as pickup_at,
    cast(tpep_dropoff_datetime as timestamp)         as dropoff_at,
    cast(pulocationid as integer)                    as pu_location_id,
    cast(dolocationid as integer)                    as do_location_id,
    cast(passenger_count as integer)                 as passenger_count,
    cast(trip_distance as double)                    as trip_distance_mi,
    cast(ratecodeid as integer)                      as ratecode_id,
    cast(store_and_fwd_flag as varchar)              as store_and_fwd_flag,
    cast(payment_type as integer)                    as payment_type,
    cast(fare_amount as double)                      as fare_amount,
    cast(extra as double)                            as extra,
    cast(mta_tax as double)                          as mta_tax,
    cast(tip_amount as double)                       as tip_amount,
    cast(tolls_amount as double)                     as tolls_amount,
    cast(improvement_surcharge as double)            as improvement_surcharge,
    cast(congestion_surcharge as double)             as congestion_surcharge,
    cast(airport_fee as double)                      as airport_fee,  -- matches Airport_fee too
    cast(cbd_congestion_fee as double)               as cbd_congestion_fee,
    cast(null as double)                             as ehail_fee,
    cast(total_amount as double)                     as total_amount,
    cast(null as integer)                            as trip_type,
    regexp_extract(filename, '[^/]+$')               as source_file,
    {{ source_month('filename') }}                   as source_month
from source
