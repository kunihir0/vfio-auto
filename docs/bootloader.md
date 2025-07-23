# Bootloader Module (`vfio_configurator/bootloader.py`)

The `bootloader.py` module is responsible for one of the most critical and platform-specific tasks in the VFIO setup process: configuring the bootloader to pass the necessary parameters to the Linux kernel at boot time.

## Key Functions

### `detect_bootloader()`

This function intelligently detects the bootloader being used by the system. It checks for the existence of common configuration files and commands to identify the bootloader, with support for:

-   **GRUB**: The most common bootloader, with variations for Debian, Fedora, and Arch-based systems.
-   **systemd-boot**: A simpler bootloader often used on UEFI systems.
-   **kernelstub**: A utility used by Pop!_OS to manage kernel boot parameters.
-   **LILO**: An older bootloader, included for completeness.

### `configure_kernel_parameters()`

This is the main function that orchestrates the modification of kernel parameters. It calls the appropriate helper function based on the detected bootloader. The required parameters it adds are:

-   `amd_iommu=on` or `intel_iommu=on`: To enable the IOMMU.
-   `iommu=pt`: To enable passthrough mode for better performance.
-   `rd.driver.pre=vfio-pci`: To ensure the `vfio-pci` driver loads before the standard graphics drivers.

### `modify_grub_default()`

For systems using GRUB, this function modifies the `/etc/default/grub` file. It safely adds the required kernel parameters to the `GRUB_CMDLINE_LINUX_DEFAULT` line and then triggers the appropriate command (`update-grub`, `grub-mkconfig`) to apply the changes.

### `configure_kernel_parameters_popos()`

On Pop!_OS, which uses `kernelstub`, this function uses the `kernelstub` command to add or remove kernel parameters.

### `modify_systemd_boot_entries()`

For systems with `systemd-boot`, this function finds all relevant boot entry files (e.g., in `/boot/loader/entries`) and adds the required parameters to the `options` line in each file.

## Safety and Backups

This module prioritizes safety by creating timestamped backups of any configuration file it modifies. This ensures that if anything goes wrong, the original configuration can be easily restored. The paths to these backups are tracked and included in the main cleanup script.