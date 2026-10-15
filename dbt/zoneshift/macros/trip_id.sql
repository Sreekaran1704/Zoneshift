{#
  Deterministic BIGINT trip key: <service code> * 1e14 + <file yyyymm> * 1e8 + <row in file>.
  e.g. yellow (1), file 2024-01, row 42 -> 120240100000042. Rows per file stay well under 1e8.
#}
{# Basename of a file path, and the YYYY-MM month embedded in it (cross-db, no regex groups). #}
{% macro source_file(filename_col) -%}
    {{ zs_regexp_match(filename_col, '[^/]+$') }}
{%- endmacro %}

{% macro source_month(filename_col) -%}
    {{ zs_regexp_match(source_file(filename_col), '[0-9]{4}-[0-9]{2}') }}
{%- endmacro %}

{% macro trip_id(service_code, filename_col, row_number_col) -%}
    (cast({{ service_code }} as bigint) * 100000000000000
     + cast(replace({{ source_month(filename_col) }}, '-', '') as bigint) * 100000000
     + cast({{ row_number_col }} as bigint))
{%- endmacro %}
