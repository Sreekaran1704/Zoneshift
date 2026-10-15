-- Load the staged files. {type} paths match the PUT layout used by load.py.
copy into raw.yellow_tripdata
    from @raw.zoneshift_stage/yellow/
    file_format = (type = parquet)
    match_by_column_name = case_insensitive;

copy into raw.green_tripdata
    from @raw.zoneshift_stage/green/
    file_format = (type = parquet)
    match_by_column_name = case_insensitive;

copy into raw.taxi_zone_lookup
    from @raw.zoneshift_stage/reference/taxi_zone_lookup.csv
    file_format = (type = csv skip_header = 1 field_optionally_enclosed_by = '"');

copy into raw.cbd_taxi_zones
    from @raw.zoneshift_stage/reference/cbd_taxi_zones.csv
    file_format = (type = csv skip_header = 1 field_optionally_enclosed_by = '"');

copy into raw.taxi_zone_shapes
    from @raw.zoneshift_stage/reference/taxi_zone_shapes.csv
    file_format = (type = csv skip_header = 1 field_optionally_enclosed_by = '"');

copy into raw.load_metadata
    from @raw.zoneshift_stage/reference/load_metadata.csv
    file_format = (type = csv skip_header = 1 field_optionally_enclosed_by = '"');
