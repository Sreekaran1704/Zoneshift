-- Both staging models emit the same columns in the same order, so a plain union all is safe.
select * from {{ ref('stg_yellow_trips') }}
union all
select * from {{ ref('stg_green_trips') }}
