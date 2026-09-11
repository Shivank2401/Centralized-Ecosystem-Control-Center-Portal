# COGS + geography (geo × channel)

## Model
Same client + same geo can have **multiple channels** (amazon, shopify, …).

```yaml
KNC:
  UK:
    country_currency: GBP
    default_channel: amazon
    channels:
      amazon:
        excel_sheet: Main              # upload-only
        orders_sales_channel: Amazon.co.uk
      shopify:
        excel_sheet: Shopify           # upload-only
        markets: [United Kingdom]
        vendors: [Kinetica - UK, Kinetica Sports UK]
```

## Local COGS (reports)
Always:

```
cogs/{client}/{geo}_{channel}_cogs.parquet|.csv
```

No need to store the filename in YAML — channel name *is* the stem.

| Client | Geo | Channel | File |
|--------|-----|---------|------|
| KNC | UK | amazon | `cogs/knc/uk_amazon_cogs.*` |
| KNC | UK | shopify | `cogs/knc/uk_shopify_cogs.*` |
| KNC | IE | shopify | `cogs/knc/ie_shopify_cogs.*` |

## Filters
| Channel | Field | Used by |
|---------|-------|---------|
| amazon | `orders_sales_channel` | Amazon orders sales-channel filter |
| shopify | `markets` + `vendors` | Shopify Market + Product vendor filters |

Shopify orders reads filters from `geography.yaml` → `channels.shopify` (not hardcoded).

## Excel workbook
`ESH_COGS_PATH` / `KNC_COGS_PATH` + `excel_sheet` are for **want_to_update** (Excel → Azure) only.
