# VFIO GPU Passthrough Setup Script

This script helps prepare a Linux system for VFIO GPU passthrough, specifically for passing through an AMD graphics card while keeping an NVIDIA graphics card for the host system on an AMD CPU.

## Features

- System prerequisite checks (CPU virtualization, IOMMU, etc.)
- Automatic detection of GPUs for passthrough
- IOMMU group analysis
- Configuration of VFIO modules and kernel parameters
- BTRFS filesystem detection and snapshot recommendation
- Full cleanup capability to revert all changes

## Requirements

- Python 3.6+
- Root privileges
- AMD CPU with virtualization and IOMMU support
- An AMD GPU to passthrough and NVIDIA GPU for the host

## Usage

### Setup VFIO

```bash
sudo python3 vfio.py
```

### Dry Run (Check Only)

```bash
sudo python3 vfio.py --dry-run
```

### Cleanup (Revert All Changes)

```bash
sudo python3 vfio.py --cleanup
```

## How It Works

1. The script first gathers all relevant information about your system
2. It displays a summary of what you have and what's missing
3. You can choose which components to configure
4. A cleanup script is created automatically to revert all changes

## BTRFS Support

If your system uses the BTRFS filesystem, the script will recommend creating a snapshot before making any changes. This provides an additional safety measure for reverting changes.

## Notes

- A system reboot is required after setup for changes to take effect
- You can verify the setup after reboot using `lspci -nnk | grep -A3 'VGA\|Display'`
- Use virt-manager to create a VM with the passed-through GPU
