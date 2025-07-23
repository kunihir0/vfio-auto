# CLI Module (`vfio_configurator/cli.py`)

The `cli.py` module is the heart of the `vfio-auto` application, serving as the main entry point and orchestrator for the entire VFIO configuration process. It is responsible for parsing command-line arguments, gathering system information, and coordinating the various sub-modules to perform the necessary setup tasks.

## Key Functions

### `main()`

The primary entry point of the script. It controls the overall execution flow, from initial checks to final reporting.

-   **Argument Parsing**: Calls [`parse_args()`](#parse_args) to handle command-line flags like `--dry-run`, `--cleanup`, and `--verify`.
-   **Dependency and Root Checks**: Ensures all necessary system commands are available and that the script is run with root privileges.
-   **Mode Handling**: Directs the application to different modes based on the provided arguments (e.g., standard setup, cleanup, or verification).
-   **System Info Gathering**: Invokes [`gather_system_info()`](#gather_system_info) to collect hardware and software details.
-   **User Confirmation**: Displays a summary of the system and prompts the user to proceed with the configuration.
-   **Setup Execution**: Calls [`interactive_setup()`](#interactive_setup) to perform the actual system modifications.
-   **State Management**: Saves a log of all changes and generates a cleanup script to revert them.

### `parse_args()`

This function uses Python's `argparse` module to define and parse all command-line arguments. It provides a user-friendly interface for controlling the script's behavior.

### `gather_system_info()`

A crucial function that collects a wide range of system data to inform the setup process. It checks:

-   CPU virtualization capabilities.
-   IOMMU status and kernel parameters.
-   GPU details, including vendor, model, and current driver.
-   The presence of required software like Libvirt.
-   Potential conflicts in the existing configuration.

### `interactive_setup()`

This function orchestrates the step-by-step modification of the system. It is designed to be interactive, ensuring the user is aware of each change being made. Its responsibilities include:

-   Configuring kernel parameters via the bootloader.
-   Setting up `vfio-pci` options in `modprobe.d`.
-   Updating the initramfs to include VFIO modules.
-   Recommending and creating Btrfs snapshots for safety.
-   Installing necessary virtualization packages (on supported systems).

## Execution Flow

The `cli.py` module follows a logical and safe execution path:

1.  **Analyze**: Gathers all necessary information without making any changes.
2.  **Report**: Presents a clear summary of the system's current state and the actions required.
3.  **Confirm**: Asks for explicit user approval before modifying the system.
4.  **Execute**: Performs the configuration steps one by one.
5.  **Finalize**: Saves a record of all changes and provides a cleanup script for easy reversal.