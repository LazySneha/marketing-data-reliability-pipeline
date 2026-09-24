{#
  Tenant isolation: staging and mart models land in <brand>_staging / <brand>_marts.
  Seeds are shared reference data and land in a single "reference" schema.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name == 'reference' -%}
        reference
    {%- elif custom_schema_name -%}
        {{ var('brand') }}_{{ custom_schema_name }}
    {%- else -%}
        {{ target.schema }}
    {%- endif -%}
{%- endmacro %}
