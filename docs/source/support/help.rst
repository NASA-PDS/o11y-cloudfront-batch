Help & Troubleshooting
======================

Troubleshooting, log locations, the bad-logs file, monitoring commands, and performance tuning are in the `Operations Runbook <https://github.com/NASA-PDS/o11y-cloudfront-batch/blob/main/docs/operations.md#troubleshooting>`_. The runbook covers the common failures:

* Logstash will not start
* no data in OpenSearch
* ``not authorized to perform: s3:ListAllMyBuckets`` (empty ``S3_CF_BUCKET_NAME``)
* memory pressure and slow pipelines
* parse failures

Local checks
------------

Validate a pipeline config:

.. code-block:: bash

    logstash -t -f config/logstash/config/pipelines/pipeline-pds-input-s3-en.conf

Reproduce a parsing problem by adding a test case. See `tests/README.md <https://github.com/NASA-PDS/o11y-cloudfront-batch/blob/main/tests/README.md#adding-tests-for-a-new-log-format>`_.

Getting additional help
-----------------------

* Search the `GitHub issues <https://github.com/NASA-PDS/o11y-cloudfront-batch/issues>`_.
* Contact the PDS Help Desk (see :doc:`contact`).
* Report security issues as described in ``SECURITY.md``.
