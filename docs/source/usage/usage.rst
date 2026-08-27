Usage
=====

This guide covers the day-to-day operation of PDS Web Analytics.

S3 Log Synchronization
----------------------

.. note::
   This step is NOT required if you already have files in S3.

Sync logs from PDS reporting servers to S3:

Basic Usage
~~~~~~~~~~~

.. code-block:: bash

    cd $O11Y_BATCH_HOME

    # Using the package command (recommended)
    s3-log-sync -c config/config.yaml -d /var/log/pds

Using AWS Profiles
~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # If AWS_PROFILE environment variable is set, it will be used automatically
    export AWS_PROFILE=pds-analytics
    s3-log-sync -c config/config.yaml -d /var/log/pds

    # Or explicitly specify the AWS profile
    s3-log-sync -c config/config.yaml -d /var/log/pds --aws-profile pds-analytics

Additional Options
~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Disable gzip compression
    s3-log-sync -c config/config.yaml -d /var/log/pds --no-gzip

    # Force upload even if files exist in S3
    s3-log-sync -c config/config.yaml -d /var/log/pds --force

.. note::
   The ``--aws-profile`` argument defaults to the ``AWS_PROFILE`` environment variable if it's set. If neither is provided, the command will fail with a helpful error message. All S3 uploads are performed using boto3 (not the AWS CLI).

Scheduled Synchronization
~~~~~~~~~~~~~~~~~~~~~~~~~

Set up as a cron job for automatic synchronization:

.. code-block:: bash

    # Example: sync every hour
    0 * * * * cd /path/to/o11y-cloudfront-batch && s3-log-sync -c config/config.yaml -d /var/log/pds

Logstash Processing
-------------------

Starting Logstash
~~~~~~~~~~~~~~~~~

Start Logstash with the PDS configuration:

.. code-block:: bash

    cd $O11Y_BATCH_HOME

    # Source the environment variables
    source .env

    # Pull the latest changes on the repo
    git pull

    # If anything changed, re-generate the pipeline configs
    ./scripts/logstash_build_config.sh

    # Start Logstash
    logstash -f ${O11Y_BATCH_HOME}/config/logstash/config/pipelines.yml

Running in Background
~~~~~~~~~~~~~~~~~~~~~

To run Logstash in the background:

.. code-block:: bash

    nohup $HOME/logstash/bin/logstash > $OUTPUT_LOG 2>&1&

Testing
-------

Run the comprehensive test suite:

Unit Tests
~~~~~~~~~~

.. code-block:: bash

    # Run S3 sync tests
    python -m pytest tests/test_s3_sync.py -v

Integration Tests
~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Run integration tests
    python -m unittest tests.test_logstash_integration

Test Runner Script
~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    chmod +x tests/run_tests.sh
    ./tests/run_tests.sh

The test suite validates:

* Log parsing accuracy
* Error handling
* Bad log detection
* ECS field mapping
* Output formatting
* Configuration loading with environment variables
* AWS profile handling
* boto3 S3 upload logic

Using Tox
~~~~~~~~~

Test with multiple Python versions:

.. code-block:: bash

    # Test with Python 3.12
    tox -e py312

    # Test with Python 3.13
    tox -e py313

    # Test with both versions
    tox -e py312,py313

    # Build documentation
    tox -e docs

    # Run linting
    tox -e lint

Monitoring
----------

Check Logstash Status
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Check Logstash process
    ps aux | grep logstash

Monitor Logs
~~~~~~~~~~~~

.. code-block:: bash

    # Monitor nohup logs
    source $O11Y_BATCH_HOME/.env
    tail -f $OUTPUT_LOG

    # Monitor logstash logs
    tail -f $LOGSTASH_HOME/logs/logstash-plain.log

    # Monitor bad logs
    tail -f /tmp/bad_logs_$(date +%Y-%m).txt

Data Processing
---------------

ECS Field Mapping
~~~~~~~~~~~~~~~~~

The system maps log data to Elastic Common Schema v8 fields:

* ``[source][address]`` - Client IP address
* ``[url][path]`` - Requested URL path
* ``[http][request][method]`` - HTTP method (GET, POST, etc.)
* ``[http][response][status_code]`` - HTTP status code
* ``[http][response][body][bytes]`` - Response size in bytes
* ``[user_agent][original]`` - User agent string
* ``[event][start]`` - Request timestamp
* ``[organization][name]`` - PDS node identifier

Error Handling
~~~~~~~~~~~~~~

The system handles various error conditions:

* **Bad Unicode**: Logs with invalid characters are tagged with ``bad_log``
* **Parse Failures**: Unparseable logs are tagged with ``_grok_parse_failure``
* **Invalid HTTP Methods**: Non-standard methods are tagged with ``_invalid_http_method``
* **Missing Fields**: Logs missing required fields are tagged appropriately

All error logs are stored in ``/tmp/bad_logs_YYYY-MM.txt`` with detailed error information.

Performance Tuning
------------------

For production deployments, consider these optimizations:

Instance Sizing
~~~~~~~~~~~~~~~

Use t3.xlarge or larger for high-volume processing

Batch Processing
~~~~~~~~~~~~~~~~

Adjust ``pipeline.batch.size`` in ``logstash.yml`` based on memory availability

Queue Settings
~~~~~~~~~~~~~~

Configure ``queue.max_bytes`` and ``queue.max_events`` in ``logstash.yml``

Monitoring
~~~~~~~~~~

Set up CloudWatch metrics for Logstash performance

For detailed troubleshooting information, see :doc:`support/help`.
