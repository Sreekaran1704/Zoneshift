select
    cast(locationid as integer)   as location_id,
    cast(borough as {{ dbt.type_string() }})      as borough,
    cast(zone as {{ dbt.type_string() }})         as zone,
    cast(service_zone as {{ dbt.type_string() }}) as service_zone
from {{ source('raw', 'taxi_zone_lookup') }}
