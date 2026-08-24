# OpenSearch Mappings

I got this mapping, first from ECS repo:

```
git clone https://github.com/elastic/ecs.git

git checkout v8.17.0

cp generated/elasticsearch/legacy/template.json $LS_SETTINGS_DIR/opensearch/
```

Then there were some customizations needed for it to work with OpenSearch.

1. Replace `order` with `priority`:

Was:
```
{
  "index_patterns": ["o11y-cloudfront-batch-*"],
  "mappings": { ... },
  "order":1,
  ...
}
```

Is:
```
{
  "index_patterns": ["o11y-cloudfront-batch-*"],
  "priority": 500,
  "mappings": { ... },
  ...
}
```

2. Wrap `mappings` and `settings` objects inside `template`:

Was:
```
{
  "index_patterns": ["o11y-cloudfront-batch-*"],
  "priority": 500,
  "mappings": { ... },
  "settings": { ... },
  ...
}
```

Is:
```
{
  "index_patterns": ["o11y-cloudfront-batch-*"],
  "priority": 500,
  "template": {
    "mappings": { ... },
    "settings": { ... }
  }
}
```

3. Change some ECS Types that are not supported in OpenSearch:

| ❌ Incompatible Feature  | 🔎 Affected Fields                                                              | ✅ OpenSearch-Compatible Fix                                                    |
| ----------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `match_only_text`       | `message`, `error.message`                                                      | Replace with `"type": "text"`                                                  |
| `constant_keyword`      | `data_stream.dataset`, `data_stream.namespace`, `data_stream.type`              | Replace with `"type": "keyword"`                                               |
| `flattened`             | 30+ fields like:<br>`process.pe.go_imports`, `log.syslog.structured_data`, etc. | Replace with `"type": "object"` or remove if unused                            |
| `wildcard`              | 20+ fields like:<br>`url.full`, `process.command_line`, `registry.data.strings` | Replace with `"type": "keyword"` unless OpenSearch 2.9+ and wildcard is needed |
| `synthetic_source_keep` | 50+ fields like:<br>`user.roles`, `host.mac`, `email.to.address`                | **Remove entirely** — not supported in OpenSearch                              |


```
sed -i '' 's/"type": "match_only_text"/"type": "text"/g' ecs-8.17-custom-template.json
sed -i '' '/"synthetic_source_keep": /d' ecs-8.17-custom-template.json
sed -i '' 's/"type": "constant_keyword"/"type": "keyword"/g' ecs-8.17-custom-template.json
sed -i '' 's/"type": "flattened"/"type": "object"/g' ecs-8.17-custom-template.json
sed -i '' 's/"type": "wildcard"/"type": "keyword"/g' ecs-8.17-custom-template.json
```
