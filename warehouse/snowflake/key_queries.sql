-- name: trips_by_service_month
-- Raw trips per service and file month.
select 'yellow' as service_type, regexp_substr(filename, '[0-9]{4}-[0-9]{2}') as source_month, count(*) as trips
from raw.yellow_tripdata group by 1, 2
union all
select 'green', regexp_substr(filename, '[0-9]{4}-[0-9]{2}'), count(*)
from raw.green_tripdata group by 1, 2
order by 1, 2;

-- name: cbd_vs_other_pre_post
-- Yellow pickups in CBD vs other zones, before vs after 2025-01-05 (raw, no exclusions).
select iff(c."Taxi Zone" is not null, 'cbd', 'other') as zone_group,
       iff(y.tpep_pickup_datetime >= '2025-01-05'::timestamp_ntz, 'post', 'pre') as period,
       count(*) as trips,
       median(y.fare_amount) as median_fare
from raw.yellow_tripdata y
left join raw.cbd_taxi_zones c on c."Taxi Zone" = y.PULocationID
group by 1, 2
order by 1, 2;

-- name: cbd_fee_distribution
-- CBD congestion fee values on yellow trips picked up on or after the policy start.
select cbd_congestion_fee, count(*) as trips
from raw.yellow_tripdata
where tpep_pickup_datetime >= '2025-01-05'::timestamp_ntz
group by 1
order by 1 nulls first;

-- name: trip_minutes_by_service
-- Mean trip duration in minutes (Snowflake datediff).
select 'yellow' as service_type,
       round(avg(datediff('second', tpep_pickup_datetime, tpep_dropoff_datetime) / 60.0), 4) as mean_minutes
from raw.yellow_tripdata
union all
select 'green', round(avg(datediff('second', lpep_pickup_datetime, lpep_dropoff_datetime) / 60.0), 4)
from raw.green_tripdata
order by 1;
