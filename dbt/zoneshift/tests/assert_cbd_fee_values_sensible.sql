-- After the policy start, the per-trip taxi fee should be $0.75 (trip touching the zone) or $0
-- (null allowed). Warn on any other value; error only if anomalies exceed 0.1% of post-policy trips.
{{ config(severity='warn') }}

select trip_id, pickup_at, cbd_congestion_fee
from {{ ref('fct_trips') }}
where pickup_at >= timestamp '{{ var("policy_date") }}'
  and cbd_congestion_fee is not null
  and cbd_congestion_fee not in (0, 0.75)
