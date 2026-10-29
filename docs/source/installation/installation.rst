Installation
============

This page covers a local development environment. Production runs on a PDS Cloud EC2; see the `Terraform README <https://github.com/NASA-PDS/o11y-cloudfront-batch/blob/main/terraform/README.md>`_ and the `Operations Runbook <https://github.com/NASA-PDS/o11y-cloudfront-batch/blob/main/docs/operations.md>`_.

Prerequisites
-------------

* Python 3.12 or later
* Docker, to run the Logstash integration tests
* ``envsubst`` (``gettext``), to build the pipeline configs locally
* AWS credentials, for anything that touches AWS

Install
-------

.. code-block:: bash

    git clone https://github.com/NASA-PDS/o11y-cloudfront-batch.git
    cd o11y-cloudfront-batch
    python3 -m venv venv
    source venv/bin/activate
    pip install -e '.[dev]'

Install the pre-commit hooks:

.. code-block:: bash

    pre-commit install
    pre-commit install -t pre-push
    pre-commit install -t prepare-commit-msg
    pre-commit install -t commit-msg

.. note::
   The ``detect-secrets`` hook needs a one-time setup. See the `wiki entry on Secrets <https://github.com/NASA-PDS/nasa-pds.github.io/wiki/Git-and-Github-Guide#detect-secrets>`_.

Next: :doc:`/usage/configuration`.
