Contributing to PDS Web Analytics
===================================

We welcome contributions to the PDS Web Analytics project! Whether you're fixing bugs, adding features, improving documentation, or reporting issues, your help is appreciated.

Getting Started
---------------

Repository
~~~~~~~~~~

The PDS Web Analytics repository is hosted on GitHub:

* **Repository**: https://github.com/NASA-PDS/o11y-cloudfront-batch
* **Issues**: https://github.com/NASA-PDS/o11y-cloudfront-batch/issues
* **Pull Requests**: https://github.com/NASA-PDS/o11y-cloudfront-batch/pulls

Development Setup
~~~~~~~~~~~~~~~~~

Before contributing, follow the :doc:`/installation` guide to set up your environment.

Ways to Contribute
------------------

Report Bugs
~~~~~~~~~~~

If you find a bug, please `open an issue <https://github.com/NASA-PDS/o11y-cloudfront-batch/issues/new>`_ with:

* A clear, descriptive title
* Steps to reproduce the issue
* Expected behavior
* Actual behavior
* Your environment (OS, Python version, etc.)
* Any relevant log files or error messages

Request Features
~~~~~~~~~~~~~~~~

Have an idea for a new feature? `Open an issue <https://github.com/NASA-PDS/o11y-cloudfront-batch/issues/new>`_ with:

* A clear description of the feature
* Use cases explaining why it would be useful
* Any implementation ideas you might have

Improve Documentation
~~~~~~~~~~~~~~~~~~~~~

Documentation improvements are always welcome! You can:

* Fix typos or clarify existing documentation
* Add examples or tutorials
* Improve API documentation
* Contribute to this Sphinx documentation in ``docs/source/``

Submit Code Changes
~~~~~~~~~~~~~~~~~~~

1. Make your changes in your feature branch
2. Add tests for any new functionality
3. Run the test suite to ensure everything passes:

   .. code-block:: bash

       # Run unit tests
       pytest tests/test_s3_sync.py -v

       # Run integration tests
       python -m unittest tests.test_logstash_integration

       # Test with tox
       tox -e py312,py313

4. Ensure your code follows the project's style guidelines:

   .. code-block:: bash

       # Run linting
       tox -e lint

5. Update documentation if needed
6. Commit your changes with a descriptive commit message:

   .. code-block:: bash

       git add .
       git commit -m "Add feature: brief description

       More detailed explanation of what changed and why."

7. Push to your fork:

   .. code-block:: bash

       git push origin feature/your-feature-name

8. `Create a Pull Request <https://github.com/NASA-PDS/o11y-cloudfront-batch/compare>`_ on GitHub

Pull Request Guidelines
-----------------------

When submitting a pull request:

* **Reference related issues** - Use "Fixes #123" or "Relates to #456" in the PR description
* **Describe your changes** - Explain what you changed and why
* **Keep changes focused** - One feature or fix per PR when possible
* **Add tests** - Include tests for new functionality
* **Update documentation** - Document new features or changes in behavior
* **Follow code style** - Pre-commit hooks will help enforce style guidelines
* **Be responsive** - Address review feedback promptly

Code Style
----------

This project follows these coding standards:

* **PEP 8** - Python code style guide
* **Black** - Code formatter (line length: 120)
* **Flake8** - Style guide enforcement
* **Type hints** - Use type annotations for function signatures
* **Docstrings** - Google-style docstrings for all public functions and classes

The pre-commit hooks will automatically check these for you.

Testing
-------

All contributions should include appropriate tests:

* **Unit tests** - Test individual functions and classes
* **Integration tests** - Test components working together
* **Test coverage** - Aim to maintain or improve test coverage

Run tests locally before submitting:

.. code-block:: bash

    # Quick test
    pytest -v

    # With coverage
    pytest --cov=pds -v

    # Test multiple Python versions
    tox -e py312,py313

Documentation
-------------

When updating documentation:

* Use reStructuredText format for Sphinx docs
* Keep language clear and concise
* Include code examples where helpful
* Build docs locally to check formatting:

  .. code-block:: bash

      tox -e docs
      # Or manually:
      sphinx-build -b html docs/source docs/build/html

Security Issues
---------------

If you discover a security vulnerability, please **do not** open a public issue. Instead:

1. Review the ``SECURITY.md`` file in the repository
2. Follow the responsible disclosure process outlined there
3. Contact the PDS security team directly

Code of Conduct
---------------

By participating in this project, you agree to abide by the NASA PDS code of conduct. We expect all contributors to:

* Be respectful and inclusive
* Welcome newcomers
* Focus on what is best for the community
* Show empathy towards other community members

License
-------

By contributing to PDS Web Analytics, you agree that your contributions will be licensed under the Apache License 2.0.

Questions?
----------

If you have questions about contributing:

* Check the :doc:`/installation`, :doc:`/configuration`, and :doc:`/usage` guides
* Review existing `issues <https://github.com/NASA-PDS/o11y-cloudfront-batch/issues>`_
* Ask in a `GitHub Discussion <https://github.com/NASA-PDS/o11y-cloudfront-batch/discussions>`_
* Contact the PDS Help Desk (see :doc:`contact`)

Thank You!
----------

Thank you for contributing to PDS Web Analytics! Your efforts help improve the Planetary Data System for the entire community.
