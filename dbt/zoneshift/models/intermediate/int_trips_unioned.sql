select * from {{ ref('stg_yellow_trips') }}
union all by name
select * from {{ ref('stg_green_trips') }}
