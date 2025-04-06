#!/usr/bin/env python3
"""
VFIO GPU Passthrough Setup Script for AMD GPUs.

This is a wrapper script that calls the main functionality from the vfio_configurator package.
"""

import os
import sys
import importlib.util

# Add the absolute path to the parent directory to Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# Check if vfio_configurator directory exists
vfio_config_dir = os.path.join(script_dir, "vfio_configurator")
if not os.path.isdir(vfio_config_dir):
    print(f"ERROR: vfio_configurator directory not found at {vfio_config_dir}")
    sys.exit(1)

# Import the cli module directly using importlib
cli_path = os.path.join(vfio_config_dir, "cli.py")
if not os.path.exists(cli_path):
    print(f"ERROR: cli.py not found at {cli_path}")
    sys.exit(1)

try:
    # Import the cli module using importlib
    spec = importlib.util.spec_from_file_location("vfio_configurator.cli", cli_path)
    cli_module = importlib.util.module_from_spec(spec)
    sys.modules["vfio_configurator.cli"] = cli_module
    spec.loader.exec_module(cli_module)
    
    # Call the main function directly instead of trying to access it as an attribute
    if __name__ == "__main__":
        sys.exit(cli_module.main())
except ImportError as e:
    print(f"ERROR: Could not import vfio_configurator package.")
    print(f"Import error: {e}")
    print(f"Make sure the vfio_configurator directory exists in the same directory as this script.")
    print(f"Debug: Script directory is {script_dir}")
    print(f"Debug: Python path is {sys.path}")
    sys.exit(1)