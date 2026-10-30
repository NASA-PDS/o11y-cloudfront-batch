#!/usr/bin/env python3
"""
Wrapper script for the PDS Web Analytics egress report.

This script is maintained for backward compatibility.
For new installations, use the 'egress-report' command directly.
"""

from pds.o11y_batch.egress_report import main

if __name__ == "__main__":
    main()
