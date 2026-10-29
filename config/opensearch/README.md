# OpenSearch Index Template

`ecs-8.17-custom-template.json` maps events to ECS 8.17 for indices matching `pds-weblogs-*` (priority 500). The pattern is fixed in the file: if `INDEX_PREFIX` is not `pds-weblogs`, change `index_patterns` to match.

## Apply

`scripts/logstash-deploy.sh` applies the template on every deploy as the composable template `pds-o11y-cloudfront-batch`. To apply it by hand, run this in OpenSearch UI Dev Tools with the file's contents as the body:

```
PUT _index_template/pds-o11y-cloudfront-batch
```

Verify with `GET _index_template/pds-o11y-cloudfront-batch`. A template applies to new indices only; existing indices keep their mappings.

## Regenerate from ECS

The file is the ECS `v8.17.0` legacy template with OpenSearch adjustments.

```bash
git clone https://github.com/elastic/ecs.git
git -C ecs checkout v8.17.0
cp ecs/generated/elasticsearch/legacy/template.json ecs-8.17-custom-template.json
```

Then, in the copied file:

1. Replace `"order": 1` with `"priority": 500`.
2. Wrap the top-level `mappings` and `settings` objects in `"template": { ... }`.
3. Replace the ECS field types OpenSearch does not support:

   | ECS type | Fields (examples) | Replacement |
   |---|---|---|
   | `match_only_text` | `message`, `error.message` | `text` |
   | `constant_keyword` | `data_stream.*` | `keyword` |
   | `flattened` | `process.pe.go_imports`, `log.syslog.structured_data` | `object` |
   | `wildcard` | `url.full`, `process.command_line` | `keyword` |
   | `synthetic_source_keep` | `user.roles`, `host.mac` | remove the property |

   ```bash
   sed -i 's/"type": "match_only_text"/"type": "text"/g' ecs-8.17-custom-template.json
   sed -i 's/"type": "constant_keyword"/"type": "keyword"/g' ecs-8.17-custom-template.json
   sed -i 's/"type": "flattened"/"type": "object"/g' ecs-8.17-custom-template.json
   sed -i 's/"type": "wildcard"/"type": "keyword"/g' ecs-8.17-custom-template.json
   sed -i '/"synthetic_source_keep": /d' ecs-8.17-custom-template.json
   ```

   On macOS use `sed -i ''`.
