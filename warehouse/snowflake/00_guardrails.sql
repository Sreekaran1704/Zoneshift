-- Run ONCE as ACCOUNTADMIN at the start of the (optional) Snowflake trial sprint, before loading.
-- Keeps the 30-day trial far inside its credits: one X-SMALL warehouse that suspends after 60s idle,
-- and a resource monitor that suspends it at 90% of a 50-credit quota.
create warehouse if not exists zoneshift_wh
    warehouse_size = 'XSMALL'
    auto_suspend = 60
    auto_resume = true
    initially_suspended = true;

create or replace resource monitor zoneshift_monitor
    with credit_quota = 50
    frequency = never
    start_timestamp = immediately
    triggers on 75 percent do notify
             on 90 percent do suspend
             on 100 percent do suspend_immediate;

alter warehouse zoneshift_wh set resource_monitor = zoneshift_monitor;

create database if not exists zoneshift;
create schema if not exists zoneshift.raw;
