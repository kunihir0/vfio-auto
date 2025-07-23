# PCI Module (`vfio_configurator/pci.py`)

The `pci.py` module is responsible for all interactions with the PCI subsystem. Its primary role is to identify GPUs, enumerate IOMMU groups, and determine which devices need to be bound to the `vfio-pci` driver for passthrough.

## Key Functions

### `get_pci_devices_mm()`

This function gathers detailed, machine-readable information about all PCI devices in the system using the `lspci` command. It also fetches information about the kernel drivers currently associated with each device. The results are cached to avoid redundant command executions.

### `get_gpus()`

Parses the output from `get_pci_devices_mm()` to identify all GPUs present in the system. It uses PCI class codes (e.g., `0300` for VGA compatible controller) to find graphics devices and extracts relevant information such as vendor, model, and driver.

### `find_gpu_for_passthrough()`

This function implements the logic for selecting the GPU to be used for passthrough. It specifically looks for an AMD GPU, as the script is optimized for this use case. If multiple AMD GPUs are found, it prompts the user to select one.

### `check_host_gpu_driver()`

After a passthrough GPU has been selected, this function checks the remaining GPUs to ensure that at least one has a suitable driver for the host operating system. This helps prevent a situation where the user is left with no display output on the host.

### `get_iommu_groups()`

Enumerates all IOMMU groups and the devices within them by reading from `/sys/kernel/iommu_groups`. This is a critical step for verifying that the passthrough GPU is in a viable group for passthrough.

### `find_gpu_related_devices()`

Once the passthrough GPU is known, this function finds its IOMMU group and all other PCI devices that are part of the same physical device (e.g., the GPU's associated audio device). This is essential for ensuring that all components of the GPU are passed through to the virtual machine.

### `get_device_ids()`

Extracts the unique `vendor:device` ID pairs from the list of devices identified by `find_gpu_related_devices()`. These are the IDs that will be used to configure the `vfio-pci` driver.