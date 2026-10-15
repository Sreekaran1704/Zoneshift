{#
  Dialect-specific SQL behind adapter.dispatch, so models run on DuckDB (dev) and Snowflake (prod).
  Everything else in the models is SQL both engines accept, or dbt's own cross-db macros
  (dbt.datediff, dbt.dateadd).
#}

{# First substring matching a group-free regex. #}
{% macro zs_regexp_match(col, pattern) -%}
    {{ return(adapter.dispatch('zs_regexp_match')(col, pattern)) }}
{%- endmacro %}
{% macro default__zs_regexp_match(col, pattern) -%}
    regexp_extract({{ col }}, '{{ pattern }}')
{%- endmacro %}
{% macro snowflake__zs_regexp_match(col, pattern) -%}
    regexp_substr({{ col }}, '{{ pattern }}')
{%- endmacro %}
{% macro databricks__zs_regexp_match(col, pattern) -%}
    regexp_extract({{ col }}, '{{ pattern }}', 0)
{%- endmacro %}

{# ISO day of week: 1 = Monday ... 7 = Sunday. #}
{% macro zs_iso_dow(d) -%}
    {{ return(adapter.dispatch('zs_iso_dow')(d)) }}
{%- endmacro %}
{% macro default__zs_iso_dow(d) -%}
    isodow({{ d }})
{%- endmacro %}
{% macro snowflake__zs_iso_dow(d) -%}
    dayofweekiso({{ d }})
{%- endmacro %}
{% macro databricks__zs_iso_dow(d) -%}
    extract(dayofweek_iso from {{ d }})
{%- endmacro %}

{# Full weekday name, e.g. Sunday. #}
{% macro zs_day_name(d) -%}
    {{ return(adapter.dispatch('zs_day_name')(d)) }}
{%- endmacro %}
{% macro default__zs_day_name(d) -%}
    dayname({{ d }})
{%- endmacro %}
{% macro databricks__zs_day_name(d) -%}
    date_format({{ d }}, 'EEEE')
{%- endmacro %}

{# One row per day in [start_col, end_col) of a one-row relation. #}
{% macro zs_date_spine(relation, start_col, end_col) -%}
    {{ return(adapter.dispatch('zs_date_spine')(relation, start_col, end_col)) }}
{%- endmacro %}
{% macro default__zs_date_spine(relation, start_col, end_col) -%}
    select cast(unnest(generate_series(
        cast({{ start_col }} as timestamp),
        cast({{ end_col }} as timestamp) - interval 1 day,
        interval 1 day
    )) as date) as date_day
    from {{ relation }}
{%- endmacro %}
{% macro snowflake__zs_date_spine(relation, start_col, end_col) -%}
    select date_day from (
        select dateadd(day, row_number() over (order by seq4()) - 1, w.{{ start_col }}) as date_day,
               w.{{ end_col }} as end_day
        from table(generator(rowcount => 10000)) cross join {{ relation }} as w
    )
    where date_day < end_day
{%- endmacro %}
{% macro databricks__zs_date_spine(relation, start_col, end_col) -%}
    select explode(sequence(
        cast({{ start_col }} as date),
        date_sub(cast({{ end_col }} as date), 1),
        interval 1 day
    )) as date_day
    from {{ relation }}
{%- endmacro %}

{# Zone polygon as a geometry in NY State Plane feet (EPSG:2263). #}
{% macro zs_zone_geometry(col) -%}
    {{ return(adapter.dispatch('zs_zone_geometry')(col)) }}
{%- endmacro %}
{% macro default__zs_zone_geometry(col) -%}
    {{ col }}
{%- endmacro %}
{% macro snowflake__zs_zone_geometry(col) -%}
    to_geometry({{ col }}, 2263)
{%- endmacro %}
{% macro databricks__zs_zone_geometry(col) -%}
    st_geomfromwkt({{ col }}, 2263)
{%- endmacro %}

{# Centroid of an EPSG:2263 geometry as a WGS84 point (x = lon, y = lat). #}
{% macro zs_centroid_wgs84(geom) -%}
    {{ return(adapter.dispatch('zs_centroid_wgs84')(geom)) }}
{%- endmacro %}
{% macro default__zs_centroid_wgs84(geom) -%}
    st_transform(st_centroid({{ geom }}), 'EPSG:2263', 'EPSG:4326', always_xy := true)
{%- endmacro %}
{% macro snowflake__zs_centroid_wgs84(geom) -%}
    st_transform(st_centroid({{ geom }}), 4326)
{%- endmacro %}
{% macro databricks__zs_centroid_wgs84(geom) -%}
    st_transform(st_centroid({{ geom }}), 4326)
{%- endmacro %}

{#
  fakesnow (the Snowflake emulator used in tests/CI) has no GEOMETRY functions. On that target only,
  zone border flags and centroids come from raw.zone_spatial_fallback (exported from the DuckDB
  build by prepare_warehouse_files.py --spatial-fallback). Real Snowflake and DuckDB compute them.
#}
{% macro zs_spatial_supported() -%}
    {{ return(target.name != 'fakesnow') }}
{%- endmacro %}
