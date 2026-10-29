Contributing to PDS Web Analytics
=================================

* **Repository:** https://github.com/NASA-PDS/o11y-cloudfront-batch
* **Issues:** https://github.com/NASA-PDS/o11y-cloudfront-batch/issues
* **Pull requests:** https://github.com/NASA-PDS/o11y-cloudfront-batch/pulls

Set up your environment with :doc:`/installation/installation`.

Reporting bugs and requesting features
--------------------------------------

`Open an issue <https://github.com/NASA-PDS/o11y-cloudfront-batch/issues/new>`_. For a bug, include steps to reproduce, expected and actual behavior, your environment, and relevant log output. For a feature, describe the use case.

Submitting changes
------------------

1. Make your changes on a feature branch.
2. Add tests for new functionality.
3. Run the checks:

   .. code-block:: bash

       pytest
       docker compose run --rm test
       tox -e lint

4. Update the documentation. Each topic has one home; see the documentation map in the `README <https://github.com/NASA-PDS/o11y-cloudfront-batch#documentation-map>`_.
5. Push the branch and `open a pull request <https://github.com/NASA-PDS/o11y-cloudfront-batch/compare>`_. Reference the issue ("Fixes #123"), describe what changed and why, and keep each pull request focused.

Code style
----------

PEP 8 with Black (line length 120), Flake8, type hints, and Google-style docstrings. The pre-commit hooks check these.

Documentation
-------------

Sphinx pages are reStructuredText in ``docs/source/``. Build them with ``tox -e docs``.

Security issues
---------------

Do not open a public issue. Follow ``SECURITY.md`` in the repository.

License
-------

Contributions are licensed under the Apache License 2.0. Questions: see :doc:`contact`.
