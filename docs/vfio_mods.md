# VFIO Modules Module (`vfio_configurator/vfio_mods.py`)

The `vfio_mods.py` module is responsible for configuring the VFIO kernel modules, which are at the core of the passthrough mechanism. Its primary goal is to ensure that the target GPU is claimed by the `vfio-pci` driver at boot time instead of the standard graphics driver.

## Key Functions

### `configure_vfio_modprobe()`

This is the main function of the module. It performs the following critical tasks:

1.  **Creates `vfio.conf`**: It creates or modifies the file `/etc/modprobe.d/vfio.conf`.
2.  **Specifies Device IDs**: It adds a line to this file that tells the `vfio-pci` driver which device IDs to bind to. The line looks like this:
    ```
    options vfio-pci ids=10de:1f0b,10de:10f9
    ```
3.  **Sets Driver Options**: It also sets important options like `disable_vga=1` to prevent `vfio-pci` from binding to the primary display device.
4.  **Configures Module Loading**: It ensures that the necessary VFIO modules are loaded early in the boot process by creating a file in `/etc/modules-load.d/`.

### `get_kernel_version()`

A helper function that determines the current kernel version. This is used to decide whether to include the `vfio_virqfd` module, which was integrated into the main `vfio` module in kernel version 6.2.

## How It Works

By creating a configuration file in `/etc/modprobe.d/`, this module leverages the Linux kernel's module loading system to control which driver is associated with the passthrough GPU. When the kernel discovers the GPU during the boot process, it consults the `modprobe.d` configuration and sees that the `vfio-pci` driver has claimed the specified device IDs. As a result, the standard graphics driver (e.g., `amdgpu` or `nvidia`) is prevented from initializing the device, leaving it free to be passed through to a virtual machine.