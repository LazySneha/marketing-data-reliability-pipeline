{#
  Raw keeps every version of a record. This picks the newest one per id.
  Ties on updated_at (same version delivered twice) are broken by load time.
#}
{% macro latest_version(relation) -%}
    select *
    from {{ relation }}
    qualify row_number() over (partition by id order by updated_at desc, _ingested_at desc) = 1
{%- endmacro %}
