select
    cast({{ adapter.quote('Taxi Zone') }} as integer)            as location_id,
    cast({{ adapter.quote('Polygon') }} as {{ dbt.type_string() }}) as polygon_wkt
from {{ source('raw', 'cbd_taxi_zones') }}
