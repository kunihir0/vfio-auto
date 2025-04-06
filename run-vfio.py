#!/usr/bin/env python3
"""
VFIO GPU Passthrough Setup Script for AMD GPUs - Alternative Runner

This is a simplified wrapper script that calls the main functionality from the vfio_configurator package
using direct Python module execution.
"""

import os
import sys

# Add the current directory to the Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

if __name__ == "__main__":
    # Simply import and run the cli module
    try:
        # This executes the code in cli.py, including the if __name__ == "__main__" block
        from vfio_configurator.cli import main
        sys.exit(main())
    except ImportError as e:
        print(f"ERROR: Could not import vfio_configurator package.")
        print(f"Import error: {e}")
        print(f"Make sure the vfio_configurator directory exists in the same directory as this script.")
        print(f"Debug: Script directory is {script_dir}")
        print(f"Debug: Python path is {sys.path}")
        sys.exit(1)