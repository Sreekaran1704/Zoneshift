-- Every trip in fct_trips must come from a non-excluded row of int_trips_cleaned,
-- and the clean row count must equal the non-excluded count.
with expected as (
    select count(*) as n from {{ ref('int_trips_cleaned') }} where not is_excluded
),
actual as (
    select count(*) as n from {{ ref('fct_trips') }}
)
select expected.n as expected_rows, actual.n as actual_rows
from expected, actual
where expected.n <> actual.n
