-- Hard gate for the warning above: fails if more than 0.1% of post-policy clean trips have a
-- CBD fee other than null, 0, or 0.75.
with post as (
    select
        count(*) as n_trips,
        sum(case when cbd_congestion_fee is not null
                  and cbd_congestion_fee not in (0, 0.75) then 1 else 0 end) as n_anomalies
    from {{ ref('fct_trips') }}
    where pickup_at >= timestamp '{{ var("policy_date") }}'
)
select * from post
where n_anomalies > 0.001 * n_trips
