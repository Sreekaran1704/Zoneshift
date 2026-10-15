-- cbd_congestion_fee must be null or zero for trips picked up before the policy start.
-- Severity warn: trips that start before midnight and end after the policy start can be charged,
-- and other cases are vendor-reported data issues; all are counted in docs/data_quality_report.md.
{{ config(severity='warn') }}

select trip_id, pickup_at, cbd_congestion_fee
from {{ ref('fct_trips') }}
where pickup_at < timestamp '{{ var("policy_date") }}'
  and coalesce(cbd_congestion_fee, 0) <> 0
