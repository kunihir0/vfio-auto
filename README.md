# VFIO-AUTO: Automated GPU Passthrough Configuration

`vfio-auto` is a powerful command-line tool designed to simplify and automate the setup of VFIO GPU passthrough on Linux systems. It is specifically tailored for configurations with two GPUs, where one is dedicated to the host system and the other is passed through to a virtual machine.

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
  - [Standard Setup](#standard-setup)
  - [Dry Run Mode](#dry-run-mode)
  - [Post-Reboot Verification](#post-reboot-verification)
  - [Cleanup](#cleanup)
- [Project Architecture](#project-architecture)
  - [Execution Flow](#execution-flow)
  - [Module Overview](#module-overview)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Automated System Checks**: Verifies all prerequisites, including CPU virtualization, IOMMU support, and kernel module availability.
- **Interactive Setup**: Guides the user through the configuration process with clear prompts and explanations.
- **Bootloader Configuration**: Automatically detects and configures GRUB, systemd-boot, and Pop!_OS's kernelstub.
- **Kernel Module Management**: Configures `vfio-pci` to bind to the target GPU and ensures necessary modules are loaded at boot.
- **Initramfs Updates**: Detects the appropriate initramfs generation tool (`mkinitcpio`, `dracut`, `update-initramfs`) and updates the initramfs.
- **Btrfs Snapshots**: Recommends and creates Btrfs snapshots for easy system rollback.
- **State Tracking and Cleanup**: Generates a cleanup script to revert all changes made by the tool.

## Prerequisites

Before running `vfio-auto`, ensure your system meets the following requirements:

- A Linux distribution with a modern kernel.
- Two GPUs (one for the host, one for passthrough).
- CPU with virtualization support (AMD-V or Intel VT-x) enabled in the BIOS/UEFI.
- IOMMU support enabled in the BIOS/UEFI.

## Installation

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/your-username/vfio-auto.git
    cd vfio-auto
    ```

2.  **Install dependencies:**

    The tool will check for required system commands. Ensure you have `pciutils` and other common system utilities installed. For Arch-based systems, the tool can also help install `qemu` and `libvirt`.

## Usage

The script must be run with root privileges.

### Standard Setup

To run the standard interactive setup, execute the following command:

```bash
sudo python3 run-vfio.py
```

The script will guide you through the following steps:
1.  System information gathering and summary.
2.  GPU selection for passthrough.
3.  Kernel parameter configuration.
4.  VFIO module configuration.
5.  Initramfs update.

### Dry Run Mode

To simulate the setup process without making any changes to your system, use the `--dry-run` flag. This is highly recommended for the first run.

```bash
sudo python3 run-vfio.py --dry-run
```

### Post-Reboot Verification

After the initial setup and a system reboot, you can verify that the configuration was successful.

-   To display manual verification steps:
    ```bash
    sudo python3 run-vfio.py --verify
    ```
-   To run automated verification with interactive fixing:
    ```bash
    sudo python3 run-vfio.py --verify-auto
    ```

### Cleanup

If you need to revert the changes made by the script, you can use the generated cleanup script:

```bash
sudo ./vfio_cleanup.sh
```

Alternatively, you can run the main script with the `--cleanup` flag:

```bash
sudo python3 run-vfio.py --cleanup
```

## Project Architecture

`vfio-auto` is built with a modular architecture, ensuring a clear separation of concerns and making the codebase easy to maintain and extend.

### Execution Flow

1.  **Entry Point**: The application is launched via [`run-vfio.py`](./run-vfio.py), which calls the `main` function in [`vfio_configurator/cli.py`](./vfio_configurator/cli.py).
2.  **Argument Parsing**: The `main` function parses command-line arguments to determine the execution mode.
3.  **System Analysis**: It gathers comprehensive information about the system's hardware and software configuration.
4.  **User Interaction**: The script displays a summary and prompts the user for confirmation before proceeding with any modifications.
5.  **Configuration**: It executes the necessary steps to configure the bootloader, kernel modules, and initramfs.
6.  **State Management**: All changes are tracked, and a cleanup script is generated to allow for easy rollback.

### Module Overview

-   **[`cli.py`](./vfio_configurator/cli.py)**: The main entry point and orchestrator.
-   **[`checks.py`](./vfio_configurator/checks.py)**: Performs all prerequisite system checks.
-   **[`pci.py`](./vfio_configurator/pci.py)**: Handles PCI device and IOMMU group enumeration.
-   **[`bootloader.py`](./vfio_configurator/bootloader.py)**: Manages bootloader detection and configuration.
-   **[`vfio_mods.py`](./vfio_configurator/vfio_mods.py)**: Configures VFIO kernel modules.
-   **[`initramfs.py`](./vfio_configurator/initramfs.py)**: Updates the initramfs.
-   **[`state.py`](./vfio_configurator/state.py)**: Tracks changes and generates the cleanup script.
-   **[`reporting.py`](./vfio_configurator/reporting.py)**: Displays formatted summaries and reports.
-   **[`packages.py`](./vfio_configurator/packages.py)**: Manages package installations.
-   **[`snapshot.py`](./vfio_configurator/snapshot.py)**: Handles Btrfs snapshot creation.
-   **[`utils.py`](./vfio_configurator/utils.py)**: Provides utility functions like logging and command execution.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for any bugs or feature requests.

## License

This project is licensed under the MIT License.