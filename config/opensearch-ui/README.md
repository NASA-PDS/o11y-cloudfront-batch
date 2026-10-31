# OpenSearch UI Dashboards

`export.ndjson` is an OpenSearch Dashboards saved-objects export of the web analytics dashboards. Import it under **Dashboards Management > Saved objects > Import**.

The **[Batch] Archive Downloads Monitoring** dashboard counts downloads from each node's data archive, not website browsing. It does this with one dashboard-level filter, **Archive paths (all nodes)**, which is applied to the `pds-weblogs*` index pattern. The filter works on fields already in the indexed events, so changing it does not require reprocessing data.

## How the filter works

The filter is a custom query with one clause per node. A clause matches the node (`organization.name`) and any one of the node's `url.path` prefixes:

```
organization.name = <node>  AND  url.path starts with <prefix 1> OR <prefix 2> ...
```

Prefixes are case-sensitive and match from the start of `url.path`. A request counts as an archive download when its `url.path` starts with one of its node's prefixes.

## Paths in the filter

Prefixes come from the PDS node archive base paths (a crawl of the node websites on 2026-10-30). The base URLs show where each prefix is served.

| `organization.name` | `url.path` prefixes | Base URLs (standard, layout) |
|---|---|---|
| `atm` | `/PDS/data/`, `/PDS/data/PDS4/` | `https://pds-atmospheres.nmsu.edu/PDS/data/` (PDS3, by volume or dataset); `.../PDS/data/PDS4/` (PDS4, by mission) |
| `en` | `/data/store`, `/data/pds4/` | `https://pds.nasa.gov/data/pds4/` (PDS4, by bundle). `/data/store` is not in the base-path list. |
| `geo` | `/earth/`, `/mro/`, `/m2020/`, `/msl/`, `/messenger/`, `/mgn/`, `/premgn/`, `/grail/`, `/lro/`, `/lunar/`, `/insight/`, `/mer/`, `/mex/`, `/ody/`, `/mgs/`, `/radiosciencedocs/` | `https://pds-geosciences.wustl.edu/<mission>/` (PDS3 and PDS4, by mission) for each prefix |
| `img` | `/img/data/`, `/data/` | `https://planetarydata.jpl.nasa.gov/img/data/` (PDS3 and PDS4, by mission or volume); `https://pds-imaging.jpl.nasa.gov/data/` (PDS3 and PDS4, by mission) |
| `naif` | `/pub/naif/pds/`, `/pub/naif/pds/data/`, `/pub/naif/pds/pds4/` | `https://naif.jpl.nasa.gov/pub/naif/pds/data/` (PDS3, by dataset ID); `.../pds/pds4/` (PDS4, by mission). The first prefix also covers the other folders under `pds/` (`MPF/`, `doc/`, `misc/`, `wgc/`). |
| `ppi` | `/data/` | `https://pds-ppi.igpp.ucla.edu/data/` (PDS3 and PDS4, one flat directory of bundle and dataset IDs) |
| `rings` | `/pds4/bundles/`, `/pds4/archives-bundles/`, `/holdings/volumes/` | `https://pds-rings.seti.org/pds4/bundles/` (PDS4, by bundle); `.../pds4/archives-bundles/` (PDS4 tar.gz archives); `.../holdings/volumes/` (PDS3, by volume set) |
| `sbn` | `/pds4/`, `/pds3/`, `/holdings/` | `https://sbnarchive.psi.edu/pds4/` (PDS4) and `.../pds3/` (PDS3); `https://pds-smallbodies.astro.umd.edu/holdings/` (PDS3 and PDS4, flat, by bundle) |

Some prefixes are not confirmed against live data. The crawl could not reach every host, and a few paths (SBN `/pds3/`, IMG `/data/`) are from prior knowledge or are likely aliases. Confirm each prefix against `url.path` values in OpenSearch before relying on it.

### Not in the filter

| Source | Why |
|---|---|
| IMG, USGS (`pdsimage2` host) | Downloads are served by CloudFront distributions whose logs are not yet loaded into OpenSearch. See [Adding the USGS Imaging archive](#adding-the-usgs-imaging-archive). |
| EN PDS3 (`/data/pds3/`) | Not included. |
| HiRISE, LROC, LOLA | Data nodes with no logs available. |

## Adding the USGS Imaging archive

The USGS Imaging archive (`https://pdsimage2.wr.usgs.gov/`) is a JavaScript application on top of one CloudFront distribution per mission. The browser downloads files directly from the distribution's own hostname, so:

- A file's `url.path` is its path inside the distribution, for example `/NIMS/go_1006/aareadme.txt` for Galileo. It does not include the mission name used on the site (`/Galileo/`), so mission path prefixes do not match.
- Each distribution has its own hostname, which CloudFront logs as the host header and the pipeline stores in `url.domain`.

So the filter should match the distribution hostnames in `url.domain`, not path prefixes. Once the distributions' CloudFront logs are loaded, add one clause to the filter: the `organization.name` the logs are loaded under, and `url.domain` equal to any of the distribution hostnames. Hostnames avoid listing hundreds of volume folders that change as volumes are added.

Get the current list of distributions from the site's own script, which maps each mission path to a distribution:

```bash
WORKDIR="$(mktemp -d)"
SITE="https://pdsimage2.wr.usgs.gov"
curl -sS -o "${WORKDIR}/main.js" "${SITE}/index-style/js/main.js"
grep -o -E 'Path:"[^"]+",URL:"https://[a-z0-9]+\.cloudfront\.net"' "${WORKDIR}/main.js"
```

To see what a distribution holds, list its top-level folders. Each distribution answers a standard S3 listing request:

```bash
DISTRIBUTION_URL="<distribution URL from the list above>"
curl -sS "${DISTRIBUTION_URL}/?delimiter=/"
```

The `Prefix` values under `CommonPrefixes` in the XML are the top-level folders. A few distributions refuse the listing with HTTP 403; their hostnames still work for the `url.domain` match. Repeat the first command before adding the clause, because the site's list of distributions can change.

## Changing the filter

Edit it in Dashboards, not in the file: the export stores the filter twice (as a query and as a string of the same query), and both must match.

1. Open the dashboard, edit the **Archive paths (all nodes)** filter, and use the **Custom DSL** option.
2. Add or remove `prefix` entries under the node's `url.path` clause, or add a clause for a node, and save the filter and the dashboard.
3. Export the dashboard with its related objects under **Dashboards Management > Saved objects**, and replace `export.ndjson` with the result.
