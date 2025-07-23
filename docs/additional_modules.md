# Additional Modules

This document covers the functionality of the remaining modules in the `vfio_configurator` directory, which provide reporting, package management, snapshot capabilities, and various utility functions.

## Reporting Module (`vfio_configurator/reporting.py`)

The `reporting.py` module is responsible for presenting clear and readable information to the user.

-   **`display_system_summary()`**: This function takes the gathered system information and displays it in a well-formatted summary. It uses color-coded icons to indicate the status of each check, making it easy for the user to see what is configured correctly and what needs attention.
-   **`verify_after_reboot()`**: This function provides a set of steps to verify the VFIO configuration after a reboot. It can be run in a manual mode, which simply displays the commands to run, or an automated mode, which executes the checks and offers to fix any issues.

## Packages Module (`vfio_configurator/packages.py`)

The `packages.py` module handles the installation of necessary virtualization software.

-   **`setup_minimal_qemu_environment()`**: This function is primarily designed for Arch-based systems. It installs `qemu`, `libvirt`, and `virt-manager`, and also handles the configuration of the `libvirt` service and user permissions. For other distributions, it provides clear instructions on which packages to install manually.

## Snapshot Module (`vfio_configurator/snapshot.py`)

The `snapshot.py` module integrates with the Btrfs filesystem to provide a powerful rollback mechanism.

-   **`create_btrfs_snapshot_recommendation()`**: If the system is using Btrfs, this function will recommend creating a snapshot before any changes are made. It can automatically create the snapshot, providing a safe and reliable way to restore the system to its original state if anything goes wrong.

## Utils Module (`vfio_configurator/utils.py`)

The `utils.py` module contains a collection of helper functions used throughout the application.

-   **Logging Functions**: A set of functions (`log_info`, `log_success`, `log_warning`, `log_error`, `log_debug`) provide color-coded and formatted output to the console.
-   **`run_command()`**: A robust wrapper around Python's `subprocess` module for executing shell commands. It includes handling for dry-run mode, error logging, and capturing output.
-   **`create_timestamped_backup()`**: A utility for creating timestamped backups of files, which is used extensively by other modules before they modify any system configuration.