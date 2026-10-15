select
    cast(locationid as integer)   as location_id,
    cast(borough as varchar)      as borough,
    cast(zone as varchar)         as zone,
    cast(service_zone as varchar) as service_zone
from {{ source('raw', 'taxi_zone_lookup') }}
