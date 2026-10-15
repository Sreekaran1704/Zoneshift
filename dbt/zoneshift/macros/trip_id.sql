{#
  Deterministic BIGINT trip key: <service code> * 1e14 + <file yyyymm> * 1e8 + <row in file>.
  e.g. yellow (1), file 2024-01, row 42 -> 120240100000042. Rows per file stay well under 1e8.
#}
{% macro source_month(filename_col) -%}
    regexp_extract({{ filename_col }}, '(\d{4}-\d{2})\.parquet$', 1)
{%- endmacro %}

{% macro trip_id(service_code, filename_col, row_number_col) -%}
    (cast({{ service_code }} as bigint) * 100000000000000
     + cast(replace({{ source_month(filename_col) }}, '-', '') as bigint) * 100000000
     + cast({{ row_number_col }} as bigint))
{%- endmacro %}
