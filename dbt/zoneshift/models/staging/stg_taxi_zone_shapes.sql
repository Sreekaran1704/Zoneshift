select
    cast(locationid as integer) as location_id,
    geom                        -- NY State Plane (EPSG:2263), US feet
from {{ source('raw', 'taxi_zone_shapes') }}
