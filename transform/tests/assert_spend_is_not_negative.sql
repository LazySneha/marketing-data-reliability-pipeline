select ad_spend_id, spend
from {{ ref('stg_ad_spend') }}
where spend < 0
