select
    cast("Taxi Zone" as integer) as location_id,
    cast("Polygon" as varchar)   as polygon_wkt
from {{ source('raw', 'cbd_taxi_zones') }}
