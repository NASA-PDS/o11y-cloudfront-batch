Help & Troubleshooting
======================

This page covers common issues and troubleshooting steps for PDS Web Analytics.

Common Issues
-------------

Logstash Won't Start
~~~~~~~~~~~~~~~~~~~~

**Symptoms**: Logstash fails to start or exits immediately.

**Solutions**:

1. Check Java installation:

   .. code-block:: bash

       java -version

2. Verify configuration syntax:

   .. code-block:: bash

       logstash -t -f config_file.conf

3. Check file permissions:

   .. code-block:: bash

       ls -la config/logstash/config/

4. Review Logstash logs:

   .. code-block:: bash

       tail -f $LOGSTASH_HOME/logs/logstash-plain.log

No Data in OpenSearch
~~~~~~~~~~~~~~~~~~~~~

**Symptoms**: Logstash is running but no data appears in OpenSearch.

**Solutions**:

1. Verify AWS credentials and permissions
2. Check S3 bucket access:

   .. code-block:: bash

       aws s3 ls s3://your-bucket-name/ --profile your-profile

3. Review Logstash logs for errors:

   .. code-block:: bash

       grep -i error $LOGSTASH_HOME/logs/logstash-plain.log

4. Verify OpenSearch endpoint is accessible
5. Check OpenSearch index patterns in the dashboard

High Memory Usage
~~~~~~~~~~~~~~~~~

**Symptoms**: Logstash consuming excessive memory.

**Solutions**:

1. Adjust ``pipeline.batch.size`` in ``logstash.yml``:

   .. code-block:: yaml

       pipeline.batch.size: 125  # Default is 125, try lowering to 50-100

2. Reduce ``pipeline.workers`` if needed:

   .. code-block:: yaml

       pipeline.workers: 2  # Adjust based on CPU cores

3. Monitor system resources:

   .. code-block:: bash

       top -p $(pgrep -f logstash)

Parse Failures
~~~~~~~~~~~~~~

**Symptoms**: Logs appearing in bad logs file or tagged with ``_grok_parse_failure``.

**Solutions**:

1. Check log format matches expected patterns
2. Review bad logs file for specific issues:

   .. code-block:: bash

       tail -f /tmp/bad_logs_$(date +%Y-%m).txt

3. Update grok patterns in ``config/logstash/config/shared/pds-filter.conf`` if needed
4. Validate log files are not corrupted:

   .. code-block:: bash

       gunzip -t your-log-file.gz

S3 Sync Issues
~~~~~~~~~~~~~~

**Symptoms**: Files not uploading to S3 or sync command failing.

**Solutions**:

1. Verify AWS credentials:

   .. code-block:: bash

       aws sts get-caller-identity --profile your-profile

2. Check AWS_PROFILE is set or passed as argument:

   .. code-block:: bash

       echo $AWS_PROFILE
       # or
       s3-log-sync --aws-profile your-profile ...

3. Verify S3 bucket exists and is accessible:

   .. code-block:: bash

       aws s3 ls s3://your-bucket-name/ --profile your-profile

4. Check for error messages in the sync output
5. Ensure sufficient disk space for gzip operations:

   .. code-block:: bash

       df -h

Environment Variable Issues
~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptoms**: Configuration not loading correctly or ``envsubst`` errors.

**Solutions**:

1. Verify ``envsubst`` is installed:

   .. code-block:: bash

       envsubst --help

2. Check environment variables are set:

   .. code-block:: bash

       echo $S3_BUCKET_NAME
       echo $OPENSEARCH_URL

3. Source your ``.env`` file:

   .. code-block:: bash

       source $O11Y_BATCH_HOME/.env

Log Locations
-------------

Important log files and their locations:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Log Type
     - Location
   * - Logstash logs
     - ``/var/log/logstash/`` or ``$LOGSTASH_HOME/logs/``
   * - Bad logs
     - ``/tmp/bad_logs_YYYY-MM.txt``
   * - Test output
     - ``target/test/``
   * - Nohup output
     - ``$OUTPUT_LOG`` (as defined in your environment)

Debugging Tips
--------------

Enable Verbose Logging
~~~~~~~~~~~~~~~~~~~~~~

For Logstash:

.. code-block:: bash

    logstash -f config.conf --log.level=debug

For Python scripts:

.. code-block:: python

    import logging
    logging.basicConfig(level=logging.DEBUG)

Test Configuration Syntax
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Test Logstash configuration
    logstash -t -f config/logstash/config/pipelines.yml

    # Test YAML configuration
    python -c "import yaml; yaml.safe_load(open('config/config.yaml'))"

Validate Grok Patterns
~~~~~~~~~~~~~~~~~~~~~~~

Use the Grok Debugger in OpenSearch Dashboard to test patterns against sample log lines.

Check Network Connectivity
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Test S3 connectivity
    aws s3 ls --profile your-profile

    # Test OpenSearch connectivity
    curl -X GET $OPENSEARCH_URL/_cluster/health

Performance Monitoring
----------------------

Monitor Logstash Performance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Check Logstash stats API
    curl -XGET 'localhost:9600/_node/stats?pretty'

Monitor System Resources
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # CPU and memory usage
    top

    # Disk space
    df -h

    # Network usage
    iftop

Getting Additional Help
-----------------------

If you continue to experience issues:

1. Check the `GitHub Issues <https://github.com/NASA-PDS/o11y-cloudfront-batch/issues>`_ for similar problems
2. Review the detailed technical documentation in the README
3. Contact the PDS Help Desk (see :doc:`contact`)
4. For security issues, see ``SECURITY.md`` in the repository

License
-------

This project is licensed under the Apache License 2.0 - see the ``LICENSE.md`` file for details.

See Also
--------

* :doc:`/installation` - Installation instructions
* :doc:`/configuration` - Configuration guide
* :doc:`/usage` - Usage guide
* :doc:`contribute` - Contributing to the project
* :doc:`contact` - Contact information
