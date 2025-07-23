# Checks Module (`vfio_configurator/checks.py`)

The `checks.py` module is dedicated to performing a series of prerequisite checks to ensure the system is ready for VFIO passthrough configuration. These checks are crucial for preventing errors and ensuring the setup process can proceed smoothly.

## Key Functions

### `check_root()`

Verifies that the script is being executed with root privileges (`sudo`). This is a fundamental requirement, as many of the configuration steps involve modifying system files and settings.

### `check_dependencies()`

Scans the system for the presence of essential command-line tools required by the script. This includes:

-   `lspci`: For listing PCI devices.
-   `grep`, `awk`, `sed`: For text processing.
-   Bootloader-specific commands (`update-grub`, `grub-mkconfig`, `kernelstub`).
-   Initramfs tools (`mkinitcpio`, `dracut`, `update-initramfs`).

### `check_cpu_virtualization()`

Inspects `/proc/cpuinfo` to confirm that CPU virtualization is enabled. It looks for the `svm` flag on AMD CPUs and the `vmx` flag on Intel CPUs. This is a non-negotiable requirement for running virtual machines.

### `check_secure_boot()`

Determines if Secure Boot is enabled, as it can interfere with loading unsigned kernel modules like `vfio-pci`. It uses `mokutil` if available or falls back to checking EFI variables.

### `check_iommu()`

Reads the kernel command line (`/proc/cmdline`) to check if IOMMU is enabled (`amd_iommu=on` or `intel_iommu=on`). It also checks for the recommended `iommu=pt` (passthrough mode) parameter.

### `check_kernel_cmdline_conflicts()`

Scans the kernel command line for any existing `vfio-pci.ids` entries. This check helps prevent conflicts with the script's method of managing VFIO device IDs via `modprobe.d`.

### `check_vfio_modules()`

Uses `lsmod` to check if the required VFIO modules (`vfio`, `vfio_iommu_type1`, `vfio_pci`) are currently loaded in the kernel.

### `check_libvirt_installed()`

Verifies that essential virtualization software, such as Libvirt and QEMU, is installed. This ensures that the user will be able to create and manage virtual machines after the passthrough setup is complete.