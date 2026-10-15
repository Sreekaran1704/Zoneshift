-- Internal stage for the prepared files. PUT with auto_compress = false keeps Parquet as-is
-- (Parquet is already compressed internally).
create or replace stage raw.zoneshift_stage;
