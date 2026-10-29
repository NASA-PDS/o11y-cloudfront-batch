Configuration
=============

Environment variables
---------------------

Copy ``.env.example`` to ``.env`` and fill in the values. On the EC2 they live in ``/etc/logstash/env``.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Variable
     - Purpose
   * - ``S3_BUCKET_NAME``
     - Node logs bucket
   * - ``S3_CF_BUCKET_NAME``
     - CloudFront logs bucket (EN only)
   * - ``OPENSEARCH_URL``
     - OpenSearch endpoint URL
   * - ``INDEX_PREFIX``
     - Index prefix (default ``pds-weblogs``)
   * - ``AWS_REGION``
     - AWS region

Pipeline configuration
----------------------

.. code-block:: text

    config/logstash/config/
    ├── inputs/                 # one pds-input-s3-<node>.conf per node
    ├── shared/
    │   ├── pds-filter.conf     # parsing, ECS mapping, enrichment
    │   └── pds-output-opensearch.conf
    ├── plugins/regexes.yaml    # user-agent patterns
    ├── logstash.yml
    ├── jvm.options
    └── pipelines.yml.template

Build the per-node pipeline configs:

.. code-block:: bash

    set -a; source .env; set +a
    LS_SETTINGS_DIR=$(pwd)/config/logstash/config ./scripts/logstash_build_config.sh

The script writes ``pipelines.yml`` and one ``pipelines/pipeline-pds-input-s3-<node>.conf`` per node (input, filter, and output combined).

The node table, log formats, and ECS field mapping are in the `README <https://github.com/NASA-PDS/o11y-cloudfront-batch#data-processing>`_. The OpenSearch index template is described in `config/opensearch/README.md <https://github.com/NASA-PDS/o11y-cloudfront-batch/blob/main/config/opensearch/README.md>`_.

Next: :doc:`usage`.
