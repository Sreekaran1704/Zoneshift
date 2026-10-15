with spine as (
    select cast(d as date) as date_day
    from generate_series(
        timestamp '{{ var("analysis_start") }}',
        timestamp '{{ var("analysis_end") }}' - interval 1 day,
        interval 1 day
    ) as t(d)
),

holidays as (
    select * from {{ ref('us_federal_holidays') }}
),

base as (
    select
        spine.date_day,
        year(spine.date_day)                                            as year,
        month(spine.date_day)                                           as month,
        cast(date_trunc('month', spine.date_day) as date)               as month_start,
        isodow(spine.date_day)                                          as iso_day_of_week,
        dayname(spine.date_day)                                         as day_name,
        isodow(spine.date_day) in (6, 7)                                as is_weekend,
        holidays.holiday_name,
        holidays.holiday_date is not null                               as is_holiday,
        spine.date_day >= date '{{ var("policy_date") }}'               as post_policy,
        -- Event-study week: 0 = the 7 days starting on the policy date (2025-01-05, a Sunday)
        cast(floor(date_diff('day', date '{{ var("policy_date") }}', spine.date_day) / 7.0) as integer)
                                                                        as weeks_from_policy
    from spine
    left join holidays on spine.date_day = holidays.holiday_date
)

select
    *,
    bool_or(is_holiday) over (partition by weeks_from_policy) as is_holiday_week
from base
