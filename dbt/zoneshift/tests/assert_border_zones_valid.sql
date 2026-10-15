-- Border zones must exist, be in Manhattan, and not be CBD zones.
select 'invalid_border_zone' as issue, location_id
from {{ ref('dim_zone') }}
where is_border_zone and (is_cbd or borough <> 'Manhattan')
union all
select 'no_border_zones', null
where not exists (select 1 from {{ ref('dim_zone') }} where is_border_zone)
