Configuration
=============

This guide covers how to configure PDS Web Analytics for your environment.

Environment Variables
---------------------

Create a ``.env`` file in the repository root:

.. code-block:: bash

    # AWS Configuration
    export AWS_REGION=us-west-2
    export S3_BUCKET_NAME=your-pds-logs-bucket
    export OPENSEARCH_URL=https://your-opensearch-domain.us-west-2.es.amazonaws.com
    export INDEX_PREFIX=pds-o11y-cloudfront-batch

    # Logstash Configuration
    export LS_SETTINGS_DIR=$(pwd)/config/logstash/config

.. note::
   See internal wiki for details of how to populate this file with production values.

Logstash Configuration
----------------------

Configuration Structure
~~~~~~~~~~~~~~~~~~~~~~~

The Logstash configuration follows this structure:

.. code-block:: text

    config/logstash/config/
    ├── inputs/                    # S3 input configurations for each PDS node
    │   ├── pds-input-s3-atm.conf
    │   ├── pds-input-s3-en.conf
    │   ├── pds-input-s3-geo.conf
    │   ├── pds-input-s3-img.conf
    │   ├── pds-input-s3-naif.conf
    │   ├── pds-input-s3-ppi.conf
    │   ├── pds-input-s3-rings.conf
    │   └── pds-input-s3-sbn.conf
    ├── shared/                    # Shared filter and output configurations
    │   ├── pds-filter.conf       # Main processing pipeline
    │   └── pds-output-opensearch.conf
    ├── plugins/                   # Custom plugins and patterns
    │   └── regexes.yaml
    ├── logstash.yml              # Logstash main configuration
    └── pipelines.yml.template    # Pipeline definitions

Building Configuration
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    cd $O11Y_BATCH_HOME

    # Source your config
    source .env

    # Run the configuration build script
    ./scripts/logstash_build_config.sh

This script will:

* Copy the pipelines template and replace the env variables to ``pipelines.yml``
* Create individual pipeline configuration files for each PDS node
* Combine input, filter, and output configurations automatically

S3 Log Sync Configuration
--------------------------

Create a configuration file based on ``config/config_example.yaml``:

.. code-block:: yaml

    s3_bucket: ${S3_BUCKET}
    s3_subdir: logs
    subdirs:
      data:
        logs:
          include:
            - "*"

The configuration supports environment variable substitution using ``${VARIABLE_NAME}`` syntax, which is processed by ``envsubst``.

OpenSearch Setup
----------------

1. Log into AWS and navigate to the OpenSearch Dashboard → Dev Tools
2. Check if template already exists (ecs-web-template):

   .. code-block:: text

       GET _cat/templates

3. If not, create the template:

   .. code-block:: text

       PUT _index_template/ecs-web-template

       # copy-paste from https://github.com/NASA-PDS/o11y-cloudfront-batch/tree/main/config/opensearch/ecs-8.17-custom-template.json

4. Verify success:

   .. code-block:: text

       GET _cat/templates

Supported Log Formats
---------------------

The system supports multiple log formats:

Apache Combined Log Format
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    192.168.1.1 - - [25/Dec/2023:10:30:45 +0000] "GET /data/file.txt HTTP/1.1" 200 1024 "http://referrer.com" "Mozilla/5.0..."

Microsoft IIS Log Format
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    2023-12-25 10:30:45 W3SVC1 192.168.1.1 GET /data/file.txt 80 - 192.168.1.100 Mozilla/5.0... 200 0 0 1024 0 15

FTP Transfer Logs
~~~~~~~~~~~~~~~~~

.. code-block:: text

    Mon Dec 25 10:30:45 2023 1 192.168.1.1 1024 /data/file.txt a _ o r user ftp 0 * c

Tomcat Access Logs
~~~~~~~~~~~~~~~~~~

.. code-block:: text

    192.168.1.1 - - [25/Dec/2023:10:30:45 +0000] "GET /webapp/data HTTP/1.1" 200 1024

PDS Node Support
----------------

The system processes logs from the following PDS nodes:

.. list-table::
   :header-rows: 1
   :widths: 10 30 20 20

   * - Node
     - Domain
     - Protocol
     - Dataset
   * - ATM
     - pds-atmospheres.nmsu.edu
     - HTTP/FTP
     - atm.http, atm.ftp
   * - EN
     - pds.nasa.gov
     - HTTP
     - en.http
   * - GEO
     - Multiple domains
     - HTTP/FTP
     - geo.http, geo.ftp
   * - IMG
     - pds-imaging.jpl.nasa.gov
     - HTTP
     - img.http
   * - NAIF
     - naif.jpl.nasa.gov
     - HTTP/FTP
     - naif.http, naif.ftp
   * - PPI
     - pds-ppi.igpp.ucla.edu
     - HTTP
     - ppi.http
   * - RINGS
     - pds-rings.seti.org
     - HTTP
     - rings.http
   * - SBN
     - Multiple domains
     - HTTP
     - sbn.http

Adding New PDS Nodes
--------------------

To add a new PDS node:

1. Create a new input configuration in ``config/logstash/config/inputs/``
2. Add the node to ``config/logstash/config/pipelines.yml.template``
3. Update the S3 sync configuration
4. Add test cases to the test framework
5. Update the documentation with node information

Next Steps
----------

After configuration, proceed to :doc:`usage` to learn how to operate the system.
