#!/usr/bin/env python3
"""
Wrapper script for PDS Web Analytics S3 Log Sync.

This script is maintained for backward compatibility.
For new installations, use the 's3-log-sync' command directly.
"""

import sys
from pds.o11y_batch.s3_sync import main

if __name__ == "__main__":
    main()
