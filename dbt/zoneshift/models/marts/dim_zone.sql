{#
  One row per TLC taxi zone. is_cbd comes from the MTA list; is_border_zone is derived from
  polygon adjacency: non-CBD Manhattan zones within border_tolerance_ft of any CBD zone.
#}
with zones as (
    select * from {{ ref('stg_taxi_zones') }}
),

cbd as (
    select location_id from {{ ref('stg_cbd_zones') }}
),

shapes as (
    select * from {{ ref('stg_taxi_zone_shapes') }}
),

cbd_shapes as (
    select shapes.geom
    from shapes
    join cbd using (location_id)
),

{% if zs_spatial_supported() %}
border as (
    select distinct shapes.location_id
    from shapes
    join zones using (location_id)
    join cbd_shapes on st_dwithin(shapes.geom, cbd_shapes.geom, {{ var('border_tolerance_ft') }})
    where zones.borough = 'Manhattan'
      and shapes.location_id not in (select location_id from cbd)
),

centroids as (
    select
        location_id,
        st_x({{ zs_centroid_wgs84('geom') }}) as lon,
        st_y({{ zs_centroid_wgs84('geom') }}) as lat
    from shapes
)
{% else %}
border as (
    select location_id from {{ source('raw', 'zone_spatial_fallback') }} where is_border_zone
),

centroids as (
    select location_id, centroid_lon as lon, centroid_lat as lat
    from {{ source('raw', 'zone_spatial_fallback') }}
)
{% endif %}

select
    zones.location_id,
    zones.borough,
    zones.zone,
    zones.service_zone,
    zones.location_id in (select location_id from cbd)      as is_cbd,
    zones.location_id in (select location_id from border)   as is_border_zone,
    zones.location_id in (264, 265)                         as is_unknown_zone,
    round(centroids.lon, 6)                                 as centroid_lon,
    round(centroids.lat, 6)                                 as centroid_lat
from zones
left join centroids using (location_id)
