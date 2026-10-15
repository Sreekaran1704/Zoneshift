select
    cast(locationid as integer) as location_id,
    {% if zs_spatial_supported() -%}
    {{ zs_zone_geometry('geom') }} as geom  -- NY State Plane (EPSG:2263), US feet
    {%- else -%}
    geom                                    -- WKT text (no GEOMETRY type on fakesnow)
    {%- endif %}
from {{ source('raw', 'taxi_zone_shapes') }}
