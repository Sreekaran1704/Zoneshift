-- Raw tables, mirroring the DuckDB raw schema column-for-column. Trip files come from
-- ingestion/prepare_warehouse_files.py, which adds filename (basename) and file_row_number.
-- Unquoted names are case-insensitive, so COPY ... MATCH_BY_COLUMN_NAME and the dbt staging models
-- work unchanged. Zone shapes are WKT text in NY State Plane (EPSG:2263); dbt casts to GEOMETRY.
create schema if not exists raw;

create or replace table raw.yellow_tripdata (
    VendorID integer,
    tpep_pickup_datetime timestamp_ntz,
    tpep_dropoff_datetime timestamp_ntz,
    passenger_count bigint,
    trip_distance double,
    RatecodeID bigint,
    store_and_fwd_flag varchar,
    PULocationID integer,
    DOLocationID integer,
    payment_type bigint,
    fare_amount double,
    extra double,
    mta_tax double,
    tip_amount double,
    tolls_amount double,
    improvement_surcharge double,
    total_amount double,
    congestion_surcharge double,
    Airport_fee double,
    cbd_congestion_fee double,
    filename varchar,
    file_row_number bigint
);

create or replace table raw.green_tripdata (
    VendorID integer,
    lpep_pickup_datetime timestamp_ntz,
    lpep_dropoff_datetime timestamp_ntz,
    store_and_fwd_flag varchar,
    RatecodeID bigint,
    PULocationID integer,
    DOLocationID integer,
    passenger_count bigint,
    trip_distance double,
    fare_amount double,
    extra double,
    mta_tax double,
    tip_amount double,
    tolls_amount double,
    ehail_fee double,
    improvement_surcharge double,
    total_amount double,
    payment_type bigint,
    trip_type bigint,
    congestion_surcharge double,
    cbd_congestion_fee double,
    filename varchar,
    file_row_number bigint
);

create or replace table raw.taxi_zone_lookup (
    LocationID integer,
    Borough varchar,
    Zone varchar,
    service_zone varchar
);

create or replace table raw.cbd_taxi_zones (
    "Taxi Zone" integer,
    "Polygon" varchar
);

create or replace table raw.taxi_zone_shapes (
    LocationID integer,
    zone varchar,
    borough varchar,
    geom varchar
);

create or replace table raw.load_metadata (
    window_start date,
    window_end date,
    loaded_at timestamp_ntz
);
