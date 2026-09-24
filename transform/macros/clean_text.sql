{# Lowercase, trim, and turn blanks into NULL. Used for every free-text marketing field. #}
{% macro clean_text(column) -%}
    nullif(lower(trim({{ column }})), '')
{%- endmacro %}
