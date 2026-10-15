-- dim_zone.is_cbd must cover exactly the MTA list, and every CBD zone must be in Manhattan.
with flagged as (
    select location_id, borough from {{ ref('dim_zone') }} where is_cbd
),
mta as (
    select location_id from {{ ref('stg_cbd_zones') }}
)
select 'missing_from_dim' as issue, location_id from mta
where location_id not in (select location_id from flagged)
union all
select 'not_in_mta_list', location_id from flagged
where location_id not in (select location_id from mta)
union all
select 'not_manhattan', location_id from flagged
where borough <> 'Manhattan'
