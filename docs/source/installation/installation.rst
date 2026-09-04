Installation
============

This guide will walk you through installing and setting up PDS Web Analytics.

Prerequisites
-------------

System Requirements
~~~~~~~~~~~~~~~~~~~

* **Operating System**: Linux/Unix (tested on CentOS 7.9, macOS)
* **Python**: 3.12.x or higher
* **Java**: OpenJDK 11 or higher (required for Logstash)
* **Memory**: Minimum 4GB RAM (8GB+ recommended for production)
* **Storage**: 10GB+ available disk space

Required Software
~~~~~~~~~~~~~~~~~

Python Virtual Environment
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

    # Create a virtual environment
    python3 -m venv venv

    # Activate the virtual environment
    # On Linux/macOS:
    source venv/bin/activate
    # On Windows:
    venv\Scripts\activate

AWS Credentials (boto3)
^^^^^^^^^^^^^^^^^^^^^^^

The S3 sync tool uses `boto3 <https://boto3.amazonaws.com/v1/documentation/api/latest/index.html>`_ for all S3 operations.

* You do **not** need the AWS CLI for S3 uploads
* You must have valid AWS credentials via:

  * ``~/.aws/credentials``
  * Environment variables
  * IAM role

* The ``--aws-profile`` argument or ``AWS_PROFILE`` environment variable can be used to select a profile

Logstash
^^^^^^^^

.. code-block:: bash

    # Download Logstash 8.x
    wget https://artifacts.elastic.co/downloads/logstash/logstash-8.17.0-linux-x86_64.tar.gz
    tar -xzf logstash-8.17.0-linux-x86_64.tar.gz
    ln -s $(pwd)/logstash-8.17.1 $(pwd)/logstash

    # Add to PATH
    echo 'export PATH="$(pwd)/logstash/bin:$PATH"' >> ~/.bashrc
    source ~/.bashrc

    # Verify installation
    logstash --version

Install additional Logstash plugins:

.. code-block:: bash

    # Install tld opensearch plugins:
    logstash-plugin install logstash-filter-tld
    logstash-plugin install logstash-output-opensearch

envsubst
^^^^^^^^

The ``envsubst`` command is used for environment variable substitution in configuration files.

.. code-block:: bash

    # Verify if already installed
    envsubst --help

    # On Ubuntu/Debian:
    sudo apt-get install gettext-base

    # On CentOS/RHEL:
    sudo yum install gettext

    # On macOS:
    brew install gettext

Installation Steps
------------------

1. Clone the Repository
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    git clone https://github.com/NASA-PDS/o11y-cloudfront-batch.git
    cd o11y-cloudfront-batch

    # Create O11Y_BATCH_HOME environment variable
    echo 'export O11Y_BATCH_HOME="$(pwd)"' >> ~/.bashrc
    source ~/.bashrc

2. Set Up Python Environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Create and activate virtual environment (using Python 3.12 or 3.13)
    python3 -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate

    # Install the package in development mode (dependencies will be installed automatically)
    pip install -e .

.. note::
   A legacy ``environment.yml`` file is provided for users who prefer conda, but the recommended approach is to use Python virtual environments with the package's setup.cfg configuration.

3. Verify Installation
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Verify the s3-log-sync command is available
    s3-log-sync --help

Development Installation
------------------------

For development work, install with extra developer dependencies:

.. code-block:: bash

    pip install --editable '.[dev]'

Configure pre-commit hooks:

.. code-block:: bash

    pre-commit install
    pre-commit install -t pre-push
    pre-commit install -t prepare-commit-msg
    pre-commit install -t commit-msg

.. note::
   A one-time setup is required both to support ``detect-secrets`` and in your global Git configuration. See the `wiki entry on Secrets <https://github.com/NASA-PDS/nasa-pds.github.io/wiki/Git-and-Github-Guide#detect-secrets>`_ to learn how.

Package Structure
-----------------

The PDS Web Analytics system is organized as a Python package:

.. code-block:: text

    src/pds/o11y_batch/
    ├── __init__.py          # Package initialization
    ├── s3_sync.py          # S3Sync class implementation (now uses boto3)
    └── VERSION.txt         # Package version

Next Steps
----------

After installation, proceed to :doc:`configuration` to set up the system for your environment.
