with data_window as (
    select window_start, window_end from {{ source('raw', 'load_metadata') }}
),

spine as (
    {{ zs_date_spine('data_window', 'window_start', 'window_end') }}
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
        {{ zs_iso_dow('spine.date_day') }}                              as iso_day_of_week,
        {{ zs_day_name('spine.date_day') }}                             as day_name,
        {{ zs_iso_dow('spine.date_day') }} in (6, 7)                    as is_weekend,
        holidays.holiday_name,
        holidays.holiday_date is not null                               as is_holiday,
        spine.date_day >= date '{{ var("policy_date") }}'               as post_policy,
        -- Event-study week: 0 = the 7 days starting on the policy date (2025-01-05, a Sunday)
        cast(floor({{ dbt.datediff("date '" ~ var('policy_date') ~ "'", 'spine.date_day', 'day') }} / 7.0) as integer)
                                                                        as weeks_from_policy
    from spine
    left join holidays on spine.date_day = holidays.holiday_date
)

select
    *,
    max(case when is_holiday then 1 else 0 end) over (partition by weeks_from_policy) = 1 as is_holiday_week
from base
