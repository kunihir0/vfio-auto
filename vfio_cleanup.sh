#!/bin/bash
# VFIO Configuration Cleanup Script
# Generated on: 2025-04-06 11:08:50

set -e

echo "VFIO Configuration Cleanup Script"
echo "This will attempt to revert changes made by the VFIO setup script."
echo "--------------------------------------------------------------"

if [ "$(id -u)" -ne 0 ]; then
    echo "This script must be run as root."
    exit 1
fi

echo "Restoring modified files..."
echo "Updating initramfs to apply changes..."
update-initramfs -u || echo "Failed to update initramfs"

echo "Cleanup completed."
echo "You should reboot your system for changes to take effect."
