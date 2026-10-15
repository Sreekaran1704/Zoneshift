-- The clean trip set must contain no negative metered fares.
select trip_id, fare_amount
from {{ ref('fct_trips') }}
where fare_amount < 0
