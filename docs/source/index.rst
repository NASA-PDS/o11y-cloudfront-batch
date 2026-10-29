PDS Web Analytics
=================

Batch web analytics for the Planetary Data System (PDS). Logstash reads access logs from S3 for the ATM, EN, GEO, IMG, NAIF, PPI, RINGS, and SBN nodes, parses them to Elastic Common Schema (ECS) v8, enriches them (GeoIP, reverse DNS, user agent), and writes them to OpenSearch.

Architecture
------------

.. code-block:: text

    PDS nodes --(Data Upload Manager)--> node logs bucket ----+
                                                               +--> Logstash EC2 --> OpenSearch --> Dashboards
    CloudFront --------------------> CloudFront logs bucket ---+
                                       (EN only)

OpenSearch is a shared platform managed in `o11y-platform <https://github.com/NASA-PDS/o11y-platform>`_. The full diagram, node table, and documentation map are in the `README <https://github.com/NASA-PDS/o11y-cloudfront-batch#readme>`_.

Operating the system
--------------------

Deployment, access, monitoring, and troubleshooting are documented in the repository, one home per topic:

* `Operations Runbook <https://github.com/NASA-PDS/o11y-cloudfront-batch/blob/main/docs/operations.md>`_
* `Terraform modules <https://github.com/NASA-PDS/o11y-cloudfront-batch/blob/main/terraform/README.md>`_
* `Deployment runbook (o11y-platform) <https://github.com/NASA-PDS/o11y-platform/blob/main/terraform/README.md>`_

.. toctree::
    :maxdepth: 2
    :caption: Getting Started

    /installation/installation
    /usage/configuration
    /usage/usage

.. toctree::
    :maxdepth: 2
    :caption: Support

    /support/help
    /support/contribute
    /support/contact

Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
