Usage
=====

Running Logstash
----------------

In production Logstash runs as a ``systemd --user`` service under the ``pdsops`` account on a PDS Cloud EC2. Deploying config, subset-of-nodes rollouts, re-ingesting S3 history, monitoring, and tuning are in the `Operations Runbook <https://github.com/NASA-PDS/o11y-cloudfront-batch/blob/main/docs/operations.md>`_. To connect and verify a deployment, see the `Logstash module README <https://github.com/NASA-PDS/o11y-cloudfront-batch/blob/main/terraform/logstash/README.md>`_.

Testing
-------

Run the pipeline integration tests (Logstash in Docker):

.. code-block:: bash

    docker compose run --rm test

Run the Python unit tests and lint:

.. code-block:: bash

    pytest
    tox -e lint

Run every supported Python version, lint, and the docs build with ``tox``. Details and how to add a log format are in `tests/README.md <https://github.com/NASA-PDS/o11y-cloudfront-batch/blob/main/tests/README.md>`_.

S3 log sync (deprecated)
------------------------

Nodes upload logs with Data Upload Manager. The ``s3-log-sync`` tool is kept for reference; it needs a config file based on ``config/config_example.yaml``:

.. code-block:: bash

    s3-log-sync -c config/config_example.yaml -d /var/log/pds --aws-profile "${AWS_PROFILE}"

``--no-gzip`` skips compression and ``--force`` uploads files that already exist in S3. ``--aws-profile`` defaults to ``AWS_PROFILE``.
