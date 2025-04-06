"""PCI device operations, IOMMU groups and GPU operations."""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from .utils import (
    log_info, log_success, log_warning, log_error, log_debug,
    cached_result, run_command
)


@cached_result('pci_devices_mm')
def get_pci_devices_mm(debug: bool = False) -> Optional[Dict[str, Dict[str, str]]]:
    """
    Get information about PCI devices using machine-readable lspci output.
    
    Returns:
        A dictionary mapping BDF addresses to device information dicts,
        or None on failure.
    """
    log_info("Gathering PCI device information...")

    # Check if lspci is available
    lspci_bin = shutil.which('lspci')
    if not lspci_bin:
        log_error("lspci not found. Please install pciutils.")
        return None

    # First run: Get machine readable device info
    cmd_mm = f"{lspci_bin} -mm"
    output_mm = run_command(cmd_mm, debug=debug)
    if output_mm is None:
        log_error(f"Failed to run '{cmd_mm}'")
        return None

    # Second run: Get additional driver info with -k flag
    cmd_drivers = f"{lspci_bin} -k"
    output_drivers = run_command(cmd_drivers, debug=debug)
    if output_drivers is None:
        log_warning(f"Failed to get driver information with '{cmd_drivers}'")
        # Continue with limited device info

    # Parse the machine-readable output into a dictionary by BDF
    devices: Dict[str, Dict[str, str]] = {}
    
    # Process the main device listing first
    for line in output_mm.splitlines():
        # Parse machine-readable output format: "BDF "Class" "Device" "Vendor" "RevID" "ProgIf" "SVendor" "SDevice"
        # Example: "00:00.0 "Host bridge" "RS780 Host Bridge" "Advanced Micro Devices, Inc. [AMD]" -r01 "" "Advanced Micro Devices, Inc. [AMD]" "RS880 Host Bridge""
        parts = line.strip().split(' "')
        if len(parts) < 3:
            continue
            
        bdf = parts[0].strip()
        devices[bdf] = {
            'bdf': bdf,
            'class': parts[1].strip('"'),
            'name': parts[2].strip('"'),
            'vendor': parts[3].strip('"'),
            'driver': 'None'  # Default, will be updated if available
        }

        # Extract vendor and device IDs from BDF column if possible
        id_match = re.search(r'\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\]', parts[2])
        if id_match:
            devices[bdf]['vendor_id'] = id_match.group(1)
            devices[bdf]['device_id'] = id_match.group(2)
        else:
            # Fallback: Try to find IDs in the vendor column
            id_match = re.search(r'\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\]', parts[3])
            if id_match:
                devices[bdf]['vendor_id'] = id_match.group(1)
                devices[bdf]['device_id'] = id_match.group(2)
            else:
                devices[bdf]['vendor_id'] = ''
                devices[bdf]['device_id'] = ''

        # Parse manufacturer name
        vendor_full = parts[3].strip('"')
        vendor_name = re.sub(r'\s*\[.*?\]$', '', vendor_full).strip()
        devices[bdf]['vendor'] = vendor_name

    # Process the driver information if available
    if output_drivers:
        current_bdf = None
        within_device_block = False
        lines = output_drivers.splitlines()
        for i, line in enumerate(lines):
            # New device entry begins with a BDF
            bdf_match = re.match(r'^([0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F]) ', line)
            if bdf_match:
                current_bdf = bdf_match.group(1)
                within_device_block = True
                
                # Create entry if it doesn't exist (unlikely, but just in case)
                if current_bdf not in devices:
                    devices[current_bdf] = {'bdf': current_bdf, 'driver': 'None'}
                continue
                
            # Lines with driver information are indented
            if within_device_block and current_bdf and "Kernel driver in use:" in line:
                driver = line.split("Kernel driver in use:")[1].strip()
                devices[current_bdf]['driver'] = driver
                
    log_success(f"Found {len(devices)} PCI devices.")
    log_debug(f"Example device data: {next(iter(devices.values())) if devices else None}", debug)
    return devices


def get_gpus(debug: bool = False) -> List[Dict[str, str]]:
    """
    Get information about installed GPUs using parsed PCI data.
    
    Args:
        debug: Enable debug logging.
    
    Returns:
        List of dictionaries with GPU information.
    """
    log_info("Identifying GPUs in the system...")
    pci_devices = get_pci_devices_mm(debug=debug)
    if not pci_devices:
        log_error("Failed to get PCI device information. Cannot identify GPUs.")
        return []

    gpus = []
    for bdf, device_info in pci_devices.items():
        # Basic GPU identification based on PCI class
        # 0300 = VGA compatible controller
        # 0301 = 3D controller (some newer NVIDIA devices)
        # 0302 = Display controller (some other GPUs)
        device_class = device_info.get('class', '').lower()
        if ('vga' in device_class or 
            '3d controller' in device_class or 
            'display controller' in device_class):
            
            # Extract useful fields for GPU
            gpu_info = {
                'bdf': bdf,
                'description': device_info.get('name', 'Unknown GPU'),
                'vendor': device_info.get('vendor', 'Unknown'),
                'vendor_id': device_info.get('vendor_id', ''),
                'device_id': device_info.get('device_id', ''),
                'driver': device_info.get('driver', 'None')
            }
            
            # Add vendor-specific shorthand for ease of use
            vendor_name = device_info.get('name', '').lower() + ' ' + device_info.get('vendor', '').lower()
            if debug:
                log_debug(f"GPU vendor detection - full vendor string: {vendor_name}", debug)
            
            # More robust vendor detection
            if 'nvidia' in vendor_name:
                gpu_info['vendor'] = 'NVIDIA'
                if debug:
                    log_debug(f"Identified as NVIDIA GPU: {gpu_info['description']}", debug)
            elif 'amd' in vendor_name or 'ati' in vendor_name or 'radeon' in vendor_name:
                gpu_info['vendor'] = 'AMD'
                if debug:
                    log_debug(f"Identified as AMD GPU: {gpu_info['description']}", debug)
            elif 'intel' in vendor_name:
                gpu_info['vendor'] = 'Intel'
                if debug:
                    log_debug(f"Identified as Intel GPU: {gpu_info['description']}", debug)
            
            gpus.append(gpu_info)

    if not gpus:
        log_warning("No GPUs found in the system.")
        return []

    # Display found GPUs
    log_info(f"Found {len(gpus)} GPU(s):")
    for i, gpu in enumerate(gpus):
        vendor_device_id = ""
        if gpu.get('vendor_id') and gpu.get('device_id'):
            vendor_device_id = f" [{gpu['vendor_id']}:{gpu['device_id']}]"
            
        driver_info = f" (Driver: {gpu.get('driver')})" if gpu.get('driver') != 'None' else " (No driver)"
        log_info(f"  {i+1}. {gpu.get('description')}{vendor_device_id} - {gpu.get('vendor')}{driver_info}")

    return gpus


def check_host_gpu_driver(gpus: List[Dict[str, str]], passthrough_gpu: Optional[Dict[str, str]], debug: bool = False) -> bool:
    """
    Check if a non-passthrough GPU likely has a working driver for the host.
    
    Args:
        gpus: List of GPU dictionaries from get_gpus().
        passthrough_gpu: The GPU selected for passthrough (to exclude from host check).
        debug: Enable debug logging.
        
    Returns:
        True if a non-passthrough GPU has a working driver, False otherwise.
    """
    log_info("Checking host GPU driver status...")

    passthrough_bdf = passthrough_gpu['bdf'] if passthrough_gpu else None

    host_gpus = [gpu for gpu in gpus if gpu.get('bdf') != passthrough_bdf]

    if not host_gpus:
        log_warning("No host GPU detected after excluding the passthrough GPU.")
        log_warning("System may not have a display after setup. Ensure this is intentional.")
        log_warning("You likely need a CPU with integrated graphics, or a second discrete GPU.")
        return False

    # Prioritize NVIDIA > Intel > Other for host check
    host_gpu_to_check = None
    nvidia_host_gpus = [gpu for gpu in host_gpus if gpu.get('vendor') == 'NVIDIA']
    intel_host_gpus = [gpu for gpu in host_gpus if gpu.get('vendor') == 'Intel']

    if nvidia_host_gpus:
        host_gpu_to_check = nvidia_host_gpus[0]  # Prefer NVIDIA for host
    elif intel_host_gpus:
        host_gpu_to_check = intel_host_gpus[0]  # Intel integrated graphics common for host
    else:
        host_gpu_to_check = host_gpus[0]  # Otherwise, just check the first one

    desc = host_gpu_to_check.get('description', 'Unknown Host GPU')
    # Use the potentially updated driver info fetched by get_pci_devices_mm
    driver = host_gpu_to_check.get('driver', 'None')
    vendor = host_gpu_to_check.get('vendor', 'Unknown')

    log_info(f"Selected host GPU for driver check: {desc} [{vendor}]")

    if driver and driver != 'None':
        log_success(f"Host GPU has driver: {driver}")
        return True
    else:
        log_warning(f"Host GPU appears to have no driver loaded. Display might not work after passthrough setup.")
        log_warning(f"Ensure appropriate driver (e.g., nvidia, amdgpu, i915) is installed for host GPU.")
        return False


def find_gpu_for_passthrough(gpus: List[Dict[str, str]], debug: bool = False) -> Optional[Dict[str, str]]:
    """
    Find the AMD GPU for passthrough, handling user choice if multiple.
    
    Args:
        gpus: List of GPU dictionaries from get_gpus().
        debug: Enable debug logging.
        
    Returns:
        Dictionary with the selected GPU for passthrough, or None if none available.
    """
    amd_gpus = [gpu for gpu in gpus if gpu.get('vendor') == 'AMD']
    non_amd_gpus = [gpu for gpu in gpus if gpu.get('vendor') != 'AMD']

    if not amd_gpus:
        log_warning("No AMD GPUs found for passthrough.")
        log_warning("This script is optimized for AMD GPU passthrough + other GPU for host.")
        log_warning("While NVIDIA passthrough is possible, it requires additional steps not covered here.")
        log_warning("Consider using an AMD GPU for passthrough for best results.")
        return None

    if not non_amd_gpus:
        log_warning("Only AMD GPUs found. No separate GPU available for the host.")
        log_warning("This setup requires a separate GPU for the host system.")
        log_warning("Consider adding a second GPU or using CPU integrated graphics for the host.")
        return None

    if len(amd_gpus) == 1:
        selected = amd_gpus[0]
        log_info(f"Selected the only AMD GPU for passthrough: {selected.get('description')}")
        return selected
    else:
        # Multiple AMD GPUs - ask user which one to use
        log_info("Multiple AMD GPUs found. Please select one for passthrough:")
        for i, gpu in enumerate(amd_gpus):
            log_info(f"  {i+1}. {gpu.get('description')} (Driver: {gpu.get('driver', 'None')})")
            
        # Get user input for selection
        selection = input("Enter the number of the GPU to use for passthrough: ").strip()
        try:
            index = int(selection) - 1
            if 0 <= index < len(amd_gpus):
                selected = amd_gpus[index]
                log_info(f"Selected AMD GPU for passthrough: {selected.get('description')}")
                return selected
            else:
                log_error(f"Invalid selection: {selection}. Please enter a number between 1 and {len(amd_gpus)}.")
                return None
        except ValueError:
            log_error(f"Invalid input: {selection}. Please enter a number.")
            return None


@cached_result('iommu_groups')
def get_iommu_groups(debug: bool = False) -> Optional[Dict[int, List[Dict[str, str]]]]:
    """
    Get all IOMMU groups and the devices within them.
    
    Args:
        debug: Enable debug logging.
        
    Returns:
        Dictionary mapping IOMMU group IDs to lists of device dictionaries,
        or None if IOMMU groups could not be retrieved.
    """
    log_info("Gathering IOMMU group information...")
    iommu_dir = Path("/sys/kernel/iommu_groups")
    
    if not iommu_dir.exists():
        log_error("IOMMU groups directory not found. IOMMU may not be enabled correctly.")
        log_error("Check kernel parameters: intel_iommu=on or amd_iommu=on")
        return None
        
    # Get the list of IOMMU groups
    try:
        groups = [d for d in iommu_dir.iterdir() if d.is_dir()]
    except (PermissionError, OSError) as e:
        log_error(f"Error accessing IOMMU groups: {e}")
        return None
        
    if not groups:
        log_warning("No IOMMU groups found. IOMMU may not be enabled correctly.")
        return None
        
    iommu_map: Dict[int, List[Dict[str, str]]] = {}
    
    # Get PCI device information first to enrich our IOMMU data
    pci_devices = get_pci_devices_mm(debug=debug) or {}
    
    # Process each IOMMU group
    for group_dir in sorted(groups, key=lambda d: int(d.name)):
        try:
            group_id = int(group_dir.name)
            devices_dir = group_dir / "devices"
            
            if not devices_dir.exists():
                continue
                
            devices_in_group = []
            
            for device_link in devices_dir.iterdir():
                bdf = device_link.name
                
                # Basic device info
                device_info = {
                    'bdf': bdf,
                }
                
                # Enhance with detailed PCI info if available
                if bdf in pci_devices:
                    device_info.update(pci_devices[bdf])
                    
                # Otherwise try to get minimal info directly from sysfs
                else:
                    try:
                        # Read device class from sysfs
                        class_path = device_link / "class"
                        if class_path.exists():
                            device_class = class_path.read_text().strip()
                            # Convert class code (e.g., 0x030000) to human-readable
                            if device_class.startswith("0x03"):
                                device_info['class'] = "Display Controller"
                            elif device_class.startswith("0x04"):
                                device_info['class'] = "Multimedia Controller"
                            else:
                                device_info['class'] = f"PCI Device (Class: {device_class})"
                                
                        # Read vendor and device IDs
                        vendor_path = device_link / "vendor"
                        device_id_path = device_link / "device"
                        
                        if vendor_path.exists() and device_id_path.exists():
                            vendor_id = vendor_path.read_text().strip()[2:]  # Remove "0x"
                            device_id = device_id_path.read_text().strip()[2:]  # Remove "0x"
                            device_info['vendor_id'] = vendor_id
                            device_info['device_id'] = device_id
                            
                    except (OSError, PermissionError) as e:
                        if debug:
                            log_debug(f"Error reading sysfs for {bdf}: {e}", debug)
                
                devices_in_group.append(device_info)
                
            if devices_in_group:
                iommu_map[group_id] = devices_in_group
                
        except (ValueError, OSError, PermissionError) as e:
            log_warning(f"Error processing IOMMU group {group_dir.name}: {e}")
            
    if not iommu_map:
        log_warning("No usable IOMMU groups found.")
        return None
        
    # Log summary
    group_count = len(iommu_map)
    device_count = sum(len(devices) for devices in iommu_map.values())
    log_success(f"Found {group_count} IOMMU groups containing {device_count} devices.")
    
    # Debug logging for all groups
    if debug:
        log_debug("IOMMU Groups Summary:", debug)
        for group_id, devices in sorted(iommu_map.items()):
            log_debug(f"Group {group_id} ({len(devices)} devices):", debug)
            for device in devices:
                desc = device.get('name', 'Unknown device')
                bdf = device.get('bdf', 'Unknown BDF')
                log_debug(f"  {bdf}: {desc}", debug)
                
    return iommu_map


def find_gpu_related_devices(gpu: Dict[str, str], iommu_groups: Dict[int, List[Dict[str, str]]], debug: bool = False) -> Tuple[Optional[int], List[Tuple[Dict[str, str], int]]]:
    """
    Finds the IOMMU group for the main GPU and ALL related devices (sharing the same base BDF)
    across potentially multiple groups.

    Args:
        gpu: Dictionary representing the GPU (must contain 'bdf').
        iommu_groups: The dictionary returned by get_iommu_groups.
        debug: Enable debug logging.

    Returns:
        A tuple containing:
        - The IOMMU group ID of the primary GPU function (e.g., .0 device), or None if not found.
        - A list of tuples, where each tuple is (device_dict, group_id) for ALL related devices
          (including the GPU itself and functions like audio .1). Returns empty list if none found.
    """
    if 'bdf' not in gpu or not iommu_groups:
        log_error("Invalid GPU information or IOMMU groups data.")
        return None, []

    gpu_bdf = gpu['bdf']
    log_info(f"Identifying IOMMU group and related devices for GPU at {gpu_bdf}...")

    # Expected GPU function is usually .0, Audio is .1, etc.
    # Find the base address - handle both domain:bus:device.function and bus:device.function formats
    base_bdf_match = re.match(r'(?:([0-9a-fA-F]{4}):)?([0-9a-fA-F]{2}:[0-9a-fA-F]{2})\.[0-9a-fA-F]', gpu_bdf)
    
    if not base_bdf_match:
        log_error(f"Could not parse GPU BDF: {gpu_bdf}")
        return None, []
    
    # Group 1 is optional domain, Group 2 is bus:device
    domain = base_bdf_match.group(1)
    bus_device = base_bdf_match.group(2)
    function = gpu_bdf.split('.')[-1]
    
    # Construct the base prefix - with or without domain as needed
    if domain:
        gpu_base_bdf_prefix = f"{domain}:{bus_device}"
    else:
        gpu_base_bdf_prefix = bus_device
        
    if debug:
        log_debug(f"GPU base BDF prefix: {gpu_base_bdf_prefix}", debug)

    primary_gpu_group_id: Optional[int] = None
    all_related_devices: List[Tuple[Dict[str, str], int]] = []
    found_primary_gpu = False

    # Extract the short form (without domain) of the GPU BDF for comparison
    short_gpu_bdf = gpu_bdf if ':' not in gpu_bdf or gpu_bdf.count(':') == 1 else gpu_bdf.split(':')[-2] + ':' + gpu_bdf.split(':')[-1]

    for group_id, devices_in_group in iommu_groups.items():
        for device in devices_in_group:
            device_bdf = device.get('bdf', '')
            
            # Extract the short form (without domain) of the device BDF for comparison
            short_device_bdf = device_bdf if ':' not in device_bdf or device_bdf.count(':') == 1 else device_bdf.split(':')[-2] + ':' + device_bdf.split(':')[-1]
            
            # Check if this device is part of the same PCIe device (same base BDF)
            if bus_device in device_bdf:
                # If this is the exact GPU we're looking for (primary function)
                if short_device_bdf == short_gpu_bdf or device_bdf.endswith(short_gpu_bdf):
                    primary_gpu_group_id = group_id
                    found_primary_gpu = True
                    log_debug(f"Found primary GPU device {gpu_bdf} as {device_bdf} in IOMMU group {group_id}", debug)
                    
                # Collect all related devices (including the primary GPU)
                all_related_devices.append((device, group_id))
                log_debug(f"Found related device {device_bdf} in IOMMU group {group_id}", debug)

    if not found_primary_gpu:
        log_error(f"Could not find the primary GPU device {gpu_bdf} in any IOMMU group.")
        return None, []  # Return empty list; primary GPU not found in IOMMU groups

    if primary_gpu_group_id is not None:
        log_success(f"Primary GPU is in IOMMU group {primary_gpu_group_id}")
    else:
        log_error(f"Could not determine primary GPU IOMMU group.")

    # Log summary of related devices
    if not all_related_devices:
        log_error(f"No related devices found for GPU {gpu_bdf} in IOMMU groups.")
    else:
        log_info(f"Found {len(all_related_devices)} device(s) related to GPU {gpu_bdf}:")
        for device, group_id in all_related_devices:
            device_bdf = device.get('bdf', 'Unknown')
            device_name = device.get('name', device.get('class', 'Unknown device'))
            log_info(f"  Device {device_bdf} in group {group_id}: {device_name}")

    return primary_gpu_group_id, all_related_devices


def get_device_ids(related_devices: List[Tuple[Dict[str, str], int]]) -> List[str]:
    """
    Extract unique vendor:device ID pairs from the list of related devices.
    
    Args:
        related_devices: List of tuples (device_dict, group_id) from find_gpu_related_devices().
        
    Returns:
        List of vendor:device ID strings in format "xxxx:yyyy".
    """
    ids = set()
    for device, group_id in related_devices:
        vendor_id = device.get('vendor_id', '')
        device_id = device.get('device_id', '')
        if vendor_id and device_id:
            ids.add(f"{vendor_id}:{device_id}")

    unique_ids = sorted(list(ids))
    if unique_ids:
        log_info(f"Found {len(unique_ids)} unique device IDs for passthrough:")
        for id_pair in unique_ids:
            log_info(f"  {id_pair}")
    else:
        log_warning("No device IDs found for the selected GPU and its related devices.")
        log_warning("This will prevent proper VFIO configuration.")

    return unique_ids