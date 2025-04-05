#!/usr/bin/env python3
"""
VFIO GPU Passthrough Setup Script

This script helps prepare a Linux system for VFIO GPU passthrough,
specifically for passing through an AMD graphics card while keeping
an NVIDIA GTX 1650 for the host system on an AMD CPU.

Usage:
    sudo python3 vfio.py

Requirements:
    - Python 3.6+
    - Root privileges
    - AMD CPU with virtualization and IOMMU support
    - An AMD GPU to passthrough and NVIDIA GTX 1650 for the host
"""

import os
import re
import sys
import subprocess
import shutil
from pathlib import Path
import argparse
import json
import datetime


class Colors:
    """Terminal colors for better readability."""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    ENDC = '\033[0m'


def log_info(message):
    """Print an informational message."""
    print(f"{Colors.BLUE}{Colors.BOLD}[INFO]{Colors.ENDC} {message}")


def log_success(message):
    """Print a success message."""
    print(f"{Colors.GREEN}{Colors.BOLD}[SUCCESS]{Colors.ENDC} {message}")


def log_warning(message):
    """Print a warning message."""
    print(f"{Colors.YELLOW}{Colors.BOLD}[WARNING]{Colors.ENDC} {message}")


def log_error(message):
    """Print an error message."""
    print(f"{Colors.RED}{Colors.BOLD}[ERROR]{Colors.ENDC} {message}")


def log_debug(message, debug=False):
    """Print a debug message if debug mode is enabled."""
    if debug:
        print(f"{Colors.BLUE}[DEBUG]{Colors.ENDC} {message}")


def run_command(command, dry_run=False, debug=False):
    """Run a shell command and return its output."""
    if dry_run:
        log_debug(f"Would run command: {command}", debug)
        # For certain read-only commands, we can still execute them in dry run mode
        if command.startswith(('grep', 'lspci', 'ls', 'df', 'cat', 'find', 'test', '[')):
            try:
                result = subprocess.run(
                    command, 
                    shell=True, 
                    check=True, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    universal_newlines=True
                )
                log_debug(f"Command output: {result.stdout.strip()}", debug)
                return result.stdout.strip()
            except subprocess.CalledProcessError as e:
                log_debug(f"Command would have failed: {e.stderr}", debug)
                return None
        else:
            # Simulate success for commands that would modify the system
            return "DRY-RUN-SUCCESS"
    
    try:
        result = subprocess.run(
            command, 
            shell=True, 
            check=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            universal_newlines=True
        )
        if debug:
            log_debug(f"Command output: {result.stdout.strip()}", debug)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {command}")
        log_error(f"Error output: {e.stderr}")
        return None


def check_root():
    """Check if the script is running with root privileges."""
    if os.geteuid() != 0:
        log_error("This script must be run as root (with sudo).")
        sys.exit(1)
    log_success("Running with root privileges.")


def check_cpu_virtualization():
    """Check if CPU virtualization is enabled."""
    log_info("Checking CPU virtualization...")
    
    # Check for AMD-V
    output = run_command("grep -m1 -o 'svm\\|vmx' /proc/cpuinfo")
    if output:
        virt_type = "AMD-V" if output == "svm" else "Intel VT-x"
        log_success(f"{virt_type} virtualization is available.")
        return True
    else:
        log_error("CPU virtualization not found. Please enable SVM in BIOS.")
        return False


def check_iommu():
    """Check if IOMMU is enabled."""
    log_info("Checking IOMMU status...")
    
    # Check kernel command line for IOMMU
    cmdline = Path("/proc/cmdline").read_text()
    
    if "amd_iommu=on" in cmdline and "iommu=pt" in cmdline:
        log_success("IOMMU is properly enabled.")
        return True
    else:
        log_warning("IOMMU is not properly enabled in kernel parameters.")
        return False


def check_vfio_modules():
    """Check if VFIO modules are loaded."""
    log_info("Checking VFIO modules...")
    
    required_modules = ["vfio", "vfio_iommu_type1", "vfio_pci"]
    loaded_modules = run_command("lsmod | grep -E 'vfio(_|$)' | awk '{print $1}'").split('\n')
    
    missing_modules = [module for module in required_modules if module not in loaded_modules]
    
    if missing_modules:
        log_warning(f"Missing VFIO modules: {', '.join(missing_modules)}")
        return False
    else:
        log_success("All required VFIO modules are loaded.")
        return True


def get_gpus():
    """Get information about installed GPUs."""
    log_info("Identifying GPUs in the system...")
    
    # Get all PCI devices
    lspci_output = run_command("lspci -nnk | grep -A3 'VGA\\|Display'")
    
    if not lspci_output:
        log_error("No GPUs detected in the system.")
        return []
    
    # Parse the output to identify GPUs
    gpus = []
    current_gpu = {}
    
    for line in lspci_output.split('\n'):
        if 'VGA' in line or 'Display' in line:
            if current_gpu:
                gpus.append(current_gpu)
                current_gpu = {}
            
            # Extract BDF address, vendor, device, and description
            match = re.match(r'^(\S+).*\[(\w+):(\w+)\](.*)$', line)
            if match:
                bdf, vendor_id, device_id, description = match.groups()
                current_gpu = {
                    'bdf': bdf.strip(),
                    'vendor_id': vendor_id,
                    'device_id': device_id,
                    'description': description.strip(),
                }
                
                # Identify GPU vendor
                if 'AMD' in description or 'ATI' in description:
                    current_gpu['vendor'] = 'AMD'
                elif 'NVIDIA' in description:
                    current_gpu['vendor'] = 'NVIDIA'
                elif 'Intel' in description:
                    current_gpu['vendor'] = 'Intel'
                else:
                    current_gpu['vendor'] = 'Unknown'
        
        elif current_gpu and 'Kernel driver in use:' in line:
            current_gpu['driver'] = line.split(':')[1].strip()
    
    # Add the last GPU if there is one
    if current_gpu:
        gpus.append(current_gpu)
    
    if not gpus:
        log_error("Failed to identify GPUs.")
        return []
    
    # Display found GPUs
    for i, gpu in enumerate(gpus):
        log_info(f"GPU {i+1}: {gpu['description']} [{gpu['vendor']}] at {gpu['bdf']}")
        if 'driver' in gpu:
            log_info(f"  Driver: {gpu['driver']}")
    
    return gpus


def find_gpu_for_passthrough(gpus):
    """Find the AMD GPU for passthrough."""
    amd_gpus = [gpu for gpu in gpus if gpu['vendor'] == 'AMD']
    nvidia_gpus = [gpu for gpu in gpus if gpu['vendor'] == 'NVIDIA' and '1650' in gpu['description']]
    
    if not amd_gpus:
        log_error("No AMD GPUs found for passthrough.")
        return None
    
    if not nvidia_gpus:
        log_warning("NVIDIA GTX 1650 not found. Make sure you have a GPU for the host system.")
    
    # In case of multiple AMD GPUs, ask the user to choose
    if len(amd_gpus) > 1:
        log_info("Multiple AMD GPUs found. Please choose one for passthrough:")
        for i, gpu in enumerate(amd_gpus):
            print(f"{i+1}. {gpu['description']} at {gpu['bdf']}")
        
        choice = input("Enter the number of the GPU to passthrough: ")
        try:
            index = int(choice) - 1
            if 0 <= index < len(amd_gpus):
                return amd_gpus[index]
        except ValueError:
            pass
        
        log_error("Invalid choice. Using the first AMD GPU.")
    
    return amd_gpus[0]


def get_iommu_groups():
    """Get the IOMMU groups and their devices."""
    log_info("Checking IOMMU groups...")
    
    iommu_groups = {}
    
    # Check if /sys/kernel/iommu_groups/ exists
    if not os.path.isdir('/sys/kernel/iommu_groups'):
        log_error("IOMMU groups directory not found. IOMMU might not be enabled properly.")
        return {}
    
    # Get all IOMMU groups
    for group_path in sorted(os.listdir('/sys/kernel/iommu_groups')):
        group_id = int(group_path)
        iommu_groups[group_id] = []
        
        devices_path = f"/sys/kernel/iommu_groups/{group_id}/devices"
        if os.path.isdir(devices_path):
            for device in os.listdir(devices_path):
                device_path = os.path.join(devices_path, device)
                
                # Get device details using lspci
                lspci_output = run_command(f"lspci -nns {device}")
                if lspci_output:
                    iommu_groups[group_id].append({
                        'bdf': device,
                        'description': lspci_output
                    })
    
    return iommu_groups


def find_gpu_iommu_group(gpu, iommu_groups):
    """Find the IOMMU group for a GPU and all related devices."""
    log_info(f"Finding IOMMU group for GPU at {gpu['bdf']}...")
    
    gpu_group = None
    gpu_group_devices = []
    
    for group_id, devices in iommu_groups.items():
        for device in devices:
            if gpu['bdf'] in device['bdf']:
                gpu_group = group_id
                gpu_group_devices = devices
                break
        if gpu_group is not None:
            break
    
    if gpu_group is None:
        log_error(f"Could not find IOMMU group for GPU at {gpu['bdf']}. IOMMU might not be enabled properly.")
        return None, []
    
    log_success(f"GPU is in IOMMU group {gpu_group}")
    log_info(f"This IOMMU group contains {len(gpu_group_devices)} device(s):")
    for device in gpu_group_devices:
        log_info(f"  {device['description']}")
    
    return gpu_group, gpu_group_devices


def get_device_ids(devices):
    """Extract the vendor and device IDs from devices in an IOMMU group."""
    ids = []
    for device in devices:
        # Extract vendor:device ID from the description
        match = re.search(r'\[(\w+):(\w+)\]', device['description'])
        if match:
            vendor_id, device_id = match.groups()
            id_pair = f"{vendor_id}:{device_id}"
            if id_pair not in ids:
                ids.append(id_pair)
    
    return ids


def configure_vfio_modules(device_ids, dry_run=False, debug=False):
    """Configure VFIO modules to bind the GPU for passthrough."""
    log_info("Configuring VFIO modules...")
    
    # Create or update the VFIO configuration file
    modules_path = '/etc/modprobe.d/vfio.conf'
    options_line = f"options vfio-pci ids={','.join(device_ids)} disable_vga=1"
    
    if dry_run:
        log_debug(f"Would write to {modules_path}:", debug)
        log_debug(f"Content: {options_line}", debug)
        
        # Add VFIO modules to initramfs
        modules_load_path = '/etc/modules-load.d/vfio.conf'
        vfio_modules = ["vfio", "vfio_iommu_type1", "vfio_pci", "vfio_virqfd"]
        
        log_debug(f"Would write to {modules_load_path}:", debug)
        log_debug(f"Content: {', '.join(vfio_modules)}", debug)
        
        log_success("[DRY RUN] VFIO module configuration would be updated")
        return True
    
    # Check if the file exists and update it
    if os.path.exists(modules_path):
        with open(modules_path, 'r') as f:
            content = f.read()
            
        # If the file already has a line with options vfio-pci ids=
        if re.search(r'options\s+vfio-pci\s+ids=', content):
            # Update the existing line
            new_content = re.sub(
                r'options\s+vfio-pci\s+ids=[^\s]*(\s+disable_vga=[01])?',
                options_line,
                content
            )
            with open(modules_path, 'w') as f:
                f.write(new_content)
        else:
            # Append the new line
            with open(modules_path, 'a') as f:
                f.write(f"\n{options_line}\n")
    else:
        # Create the file
        with open(modules_path, 'w') as f:
            f.write(f"{options_line}\n")
    
    log_success(f"Updated VFIO configuration in {modules_path}")
    
    # Add VFIO modules to initramfs
    modules_load_path = '/etc/modules-load.d/vfio.conf'
    vfio_modules = [
        "vfio",
        "vfio_iommu_type1",
        "vfio_pci",
        "vfio_virqfd"
    ]
    
    with open(modules_load_path, 'w') as f:
        f.write('\n'.join(vfio_modules) + '\n')
    
    log_success(f"Created module loading configuration in {modules_load_path}")
    
    return True


def configure_kernel_parameters(dry_run=False, debug=False):
    """Configure kernel parameters for IOMMU and VFIO."""
    log_info("Configuring kernel parameters...")
    
    grub_path = '/etc/default/grub'
    
    if not os.path.exists(grub_path):
        log_error(f"{grub_path} not found. Your system might not use GRUB.")
        return False
    
    # Read current GRUB configuration
    with open(grub_path, 'r') as f:
        grub_content = f.readlines()
    
    # Find the GRUB_CMDLINE_LINUX_DEFAULT line
    cmdline_line_index = None
    for i, line in enumerate(grub_content):
        if line.startswith('GRUB_CMDLINE_LINUX_DEFAULT='):
            cmdline_line_index = i
            break
    
    if cmdline_line_index is None:
        log_error("Could not find GRUB_CMDLINE_LINUX_DEFAULT line in GRUB configuration.")
        return False
    
    # Get current parameters
    line = grub_content[cmdline_line_index]
    match = re.match(r'GRUB_CMDLINE_LINUX_DEFAULT="([^"]*)"', line)
    if not match:
        log_error(f"Unexpected format in GRUB configuration: {line}")
        return False
    
    parameters = match.group(1).split()
    
    # Add required parameters if not already present
    required_params = [
        "amd_iommu=on",
        "iommu=pt",
        "rd.driver.pre=vfio-pci",
    ]
    
    # Check which parameters need to be added
    params_to_add = []
    for param in required_params:
        param_name = param.split('=')[0]
        existing_param = next((p for p in parameters if p.startswith(f"{param_name}=")), None)
        if existing_param:
            # Parameter exists, check if it needs to be updated
            if existing_param != param:
                parameters.remove(existing_param)
                params_to_add.append(param)
        else:
            params_to_add.append(param)
    
    # If no parameters need to be added, we're done
    if not params_to_add:
        log_success("Required kernel parameters are already configured.")
        return True
    
    # Add the parameters
    parameters.extend(params_to_add)
    
    if dry_run:
        log_debug(f"Would update GRUB configuration in {grub_path}", debug)
        log_debug(f"New parameters: {params_to_add}", debug)
        log_debug(f"New GRUB_CMDLINE_LINUX_DEFAULT value: {' '.join(parameters)}", debug)
        
        grub_update_command = None
        if os.path.exists('/usr/sbin/update-grub'):
            grub_update_command = 'update-grub'
        elif os.path.exists('/usr/sbin/grub2-mkconfig'):
            grub_update_command = 'grub2-mkconfig -o /boot/grub2/grub.cfg'
        elif os.path.exists('/usr/sbin/grub-mkconfig'):
            if os.path.exists('/boot/grub/grub.cfg'):
                grub_update_command = 'grub-mkconfig -o /boot/grub/grub.cfg'
            elif os.path.exists('/boot/grub2/grub.cfg'):
                grub_update_command = 'grub-mkconfig -o /boot/grub2/grub.cfg'
        
        if grub_update_command:
            log_debug(f"Would run GRUB update command: {grub_update_command}", debug)
        
        log_success("[DRY RUN] GRUB configuration would be updated")
        return True
    
    # Create backup of the original file
    shutil.copy2(grub_path, f"{grub_path}.bak")
    log_info(f"Backed up GRUB configuration to {grub_path}.bak")
    
    # Update the GRUB configuration
    grub_content[cmdline_line_index] = f'GRUB_CMDLINE_LINUX_DEFAULT="{" ".join(parameters)}"\n'
    
    with open(grub_path, 'w') as f:
        f.writelines(grub_content)
    
    log_success(f"Updated GRUB configuration with parameters: {', '.join(params_to_add)}")
    
    grub_update_command = None
    
    # Determine the correct update-grub command
    if os.path.exists('/usr/sbin/update-grub'):
        grub_update_command = 'update-grub'
    elif os.path.exists('/usr/sbin/grub2-mkconfig'):
        grub_update_command = 'grub2-mkconfig -o /boot/grub2/grub.cfg'
    elif os.path.exists('/usr/sbin/grub-mkconfig'):
        if os.path.exists('/boot/grub/grub.cfg'):
            grub_update_command = 'grub-mkconfig -o /boot/grub/grub.cfg'
        elif os.path.exists('/boot/grub2/grub.cfg'):
            grub_update_command = 'grub-mkconfig -o /boot/grub2/grub.cfg'
    
    if not grub_update_command:
        log_error("Could not find a suitable command to update GRUB.")
        log_warning("Please update your GRUB configuration manually.")
        return False
    
    log_info(f"Updating GRUB configuration with command: {grub_update_command}")
    result = run_command(grub_update_command)
    
    if result:
        log_success("GRUB configuration updated successfully.")
        return True
    else:
        log_error("Failed to update GRUB configuration.")
        return False


def update_initramfs(dry_run=False, debug=False):
    """Update the initramfs to include VFIO modules."""
    log_info("Updating initramfs...")
    
    # Determine the command to update initramfs based on the distribution
    if os.path.exists('/usr/sbin/update-initramfs'):
        initramfs_command = 'update-initramfs -u -k all'
    elif os.path.exists('/usr/bin/dracut'):
        initramfs_command = 'dracut --force --regenerate-all'
    else:
        log_error("Could not find a suitable command to update initramfs.")
        log_warning("Please update your initramfs manually.")
        return False
    
    if dry_run:
        log_debug(f"Would run initramfs update command: {initramfs_command}", debug)
        log_success("[DRY RUN] Initramfs would be updated")
        return True
    
    log_info(f"Running: {initramfs_command}")
    result = run_command(initramfs_command)
    
    if result:
        log_success("Initramfs updated successfully.")
        return True
    else:
        log_error("Failed to update initramfs.")
        return False


def check_libvirt_installed():
    """Check if libvirt and its tools are installed."""
    log_info("Checking if libvirt is installed...")
    
    required_packages = [
        "libvirt-daemon",
        "qemu-kvm",
        "virt-manager"
    ]
    
    # First, check for common package names
    if shutil.which("virsh"):
        log_success("Virsh is available. Libvirt appears to be installed.")
        return True
    
    # Try to find the package manager
    if shutil.which("apt-get"):
        pkg_list_cmd = "dpkg -l | grep -E 'libvirt|qemu|virt-manager'"
        install_cmd = "apt-get install -y libvirt-daemon qemu-kvm virt-manager"
    elif shutil.which("dnf"):
        pkg_list_cmd = "dnf list installed | grep -E 'libvirt|qemu|virt-manager'"
        install_cmd = "dnf install -y libvirt qemu-kvm virt-manager"
    elif shutil.which("pacman"):
        pkg_list_cmd = "pacman -Q | grep -E 'libvirt|qemu|virt-manager'"
        install_cmd = "pacman -S libvirt qemu virt-manager"
    else:
        log_warning("Could not determine your package manager.")
        log_warning("Please make sure libvirt, qemu-kvm, and virt-manager are installed.")
        return False
    
    result = run_command(pkg_list_cmd)
    if not result or not all(any(pkg in line for line in result.split("\n")) for pkg in required_packages):
        log_warning("Some required virtualization packages may be missing.")
        log_info(f"You can install them with: {install_cmd}")
        return False
    
    return True


def check_btrfs():
    """Check if the system is using BTRFS filesystem."""
    log_info("Checking if system uses BTRFS filesystem...")
    
    root_fs = run_command("df -T / | awk 'NR==2 {print $2}'")
    if root_fs and root_fs.lower() == "btrfs":
        log_success("BTRFS filesystem detected.")
        return True
    else:
        log_info("BTRFS filesystem not detected.")
        return False


def find_existing_vfio_snapshots():
    """Find existing VFIO BTRFS snapshots."""
    snapshot_dir = "/.snapshots"
    existing_snapshots = []
    
    if os.path.exists(snapshot_dir):
        try:
            for item in os.listdir(snapshot_dir):
                if item.startswith("pre_vfio_setup_"):
                    full_path = os.path.join(snapshot_dir, item)
                    if os.path.exists(full_path):
                        # Get creation time as a tuple (path, timestamp)
                        ctime = os.path.getctime(full_path)
                        existing_snapshots.append((full_path, ctime))
        except (PermissionError, OSError) as e:
            log_error(f"Error checking for existing snapshots: {str(e)}")
    
    # Sort by creation time (newest first)
    existing_snapshots.sort(key=lambda x: x[1], reverse=True)
    return [path for path, _ in existing_snapshots]


def create_btrfs_snapshot_recommendation(dry_run=False, debug=False):
    """Provide recommendation for creating a BTRFS snapshot."""
    # First check if there are existing snapshots
    existing_snapshots = find_existing_vfio_snapshots()
    
    if existing_snapshots:
        log_info(f"Found {len(existing_snapshots)} existing VFIO snapshot(s):")
        for i, snapshot in enumerate(existing_snapshots):
            creation_time = datetime.datetime.fromtimestamp(os.path.getctime(snapshot))
            log_info(f"  {i+1}. {snapshot} (created on {creation_time.strftime('%Y-%m-%d %H:%M:%S')})")
        
        print("\nOptions:")
        print("  1. Use the most recent existing snapshot")
        print("  2. Create a new snapshot")
        print("  3. Skip snapshot creation")
        
        choice = input("Enter your choice (1-3): ")
        
        if choice == '1':
            log_success(f"Using existing snapshot: {existing_snapshots[0]}")
            return existing_snapshots[0]
        elif choice == '3':
            log_info("Skipping snapshot creation.")
            return None
        # If choice is 2 or invalid, proceed with creating a new snapshot
    
    # Create a new snapshot
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    snapshot_name = f"pre_vfio_setup_{timestamp}"
    
    log_info("Before proceeding, it's recommended to create a BTRFS snapshot:")
    log_info(f"  sudo btrfs subvolume snapshot / /.snapshots/{snapshot_name}")
    log_info("This will allow you to revert changes if needed with:")
    log_info(f"  sudo btrfs subvolume snapshot /.snapshots/{snapshot_name} /")
    
    response = input("Do you want to create a BTRFS snapshot now? (y/n): ").lower()
    if response == 'y':
        snapshot_dir = "/.snapshots"
        if not os.path.exists(snapshot_dir):
            if dry_run:
                log_debug(f"Would create directory: {snapshot_dir}", debug)
            else:
                run_command(f"sudo mkdir -p {snapshot_dir}")
        
        snapshot_path = f"{snapshot_dir}/{snapshot_name}"
        
        if dry_run:
            log_debug(f"Would create BTRFS snapshot: {snapshot_path}", debug)
            log_success(f"[DRY RUN] BTRFS snapshot would be created at {snapshot_path}")
            return snapshot_path
        
        result = run_command(f"sudo btrfs subvolume snapshot / {snapshot_path}")
        if result:
            log_success(f"BTRFS snapshot created at {snapshot_path}")
            return snapshot_path
        else:
            log_error("Failed to create BTRFS snapshot.")
            return None
    return None


def track_change(changes, category, item, content=None):
    """Track a change made by the script."""
    if category not in changes:
        changes[category] = []
    
    changes[category].append({
        "item": item,
        "content": content,
        "timestamp": datetime.datetime.now().isoformat()
    })
    
    return changes


def create_cleanup_script(changes, dry_run=False, debug=False):
    """Create a script to revert all changes made."""
    log_info("Creating cleanup script...")
    
    script_path = "/home/xiao/Documents/source/repo/vfio/vfio_cleanup.sh"
    script_content = "#!/bin/bash\n\n"
    script_content += "# VFIO Cleanup Script\n"
    script_content += "# This script will revert the changes made by the VFIO setup script\n\n"
    
    script_content += "echo 'Starting VFIO cleanup...'\n\n"
    
    # Handle files created or modified
    if "files" in changes:
        script_content += "# Reverting file changes\n"
        for change in changes["files"]:
            if change["content"] == "created":
                script_content += f"echo 'Removing file {change['item']}'\n"
                script_content += f"rm -f '{change['item']}'\n\n"
            elif change["content"] == "modified":
                if os.path.exists(f"{change['item']}.bak"):
                    script_content += f"echo 'Restoring original file {change['item']}'\n"
                    script_content += f"cp -f '{change['item']}.bak' '{change['item']}'\n\n"
    
    # Handle initramfs updates
    if "initramfs" in changes:
        script_content += "# Updating initramfs after reverting changes\n"
        if os.path.exists('/usr/sbin/update-initramfs'):
            script_content += "update-initramfs -u -k all\n\n"
        elif os.path.exists('/usr/bin/dracut'):
            script_content += "dracut --force --regenerate-all\n\n"
    
    # Handle GRUB updates
    if "grub" in changes:
        script_content += "# Updating GRUB after reverting changes\n"
        if os.path.exists('/usr/sbin/update-grub'):
            script_content += "update-grub\n\n"
        elif os.path.exists('/usr/sbin/grub2-mkconfig'):
            script_content += "grub2-mkconfig -o /boot/grub2/grub.cfg\n\n"
        elif os.path.exists('/usr/sbin/grub-mkconfig'):
            if os.path.exists('/boot/grub/grub.cfg'):
                script_content += "grub-mkconfig -o /boot/grub/grub.cfg\n\n"
            elif os.path.exists('/boot/grub2/grub.cfg'):
                script_content += "grub-mkconfig -o /boot/grub2/grub.cfg\n\n"
    
    # Handle BTRFS snapshot
    if "btrfs" in changes:
        script_content += "# Note about BTRFS snapshot\n"
        for change in changes["btrfs"]:
            script_content += f"echo 'A BTRFS snapshot was created at {change['item']}'\n"
            script_content += "echo 'You can manually restore from this snapshot with:'\n"
            script_content += f"echo \"  sudo btrfs subvolume snapshot {change['item']} /\"\n"
            script_content += "echo 'Or delete it with:'\n"
            script_content += f"echo \"  sudo btrfs subvolume delete {change['item']}\"\n\n"
    
    script_content += "echo 'VFIO cleanup complete. Please reboot your system for changes to take effect.'\n"
    
    if dry_run:
        log_debug(f"Would create cleanup script at {script_path}", debug)
        log_debug("Script content:", debug)
        if debug:
            for line in script_content.split('\n'):
                log_debug(f"  {line}", debug)
        
        log_success("[DRY RUN] Cleanup script would be created")
        return script_path
    
    with open(script_path, "w") as f:
        f.write(script_content)
    
    os.chmod(script_path, 0o755)
    log_success(f"Cleanup script created: {script_path}")
    log_info(f"You can run this script to revert all changes made by the VFIO setup.")
    
    return script_path


def gather_system_info():
    """Gather all relevant information about the system."""
    log_info("Gathering system information...")
    
    system_info = {
        "root_privileges": os.geteuid() == 0,
        "cpu_virtualization": check_cpu_virtualization(),
        "iommu_enabled": check_iommu(),
        "vfio_modules_loaded": check_vfio_modules(),
        "btrfs_system": check_btrfs(),
        "gpus": get_gpus(),
        "libvirt_installed": check_libvirt_installed()
    }
    
    if system_info["gpus"]:
        system_info["gpu_for_passthrough"] = find_gpu_for_passthrough(system_info["gpus"])
        if system_info["gpu_for_passthrough"]:
            iommu_groups = get_iommu_groups()
            if iommu_groups:
                system_info["iommu_groups"] = iommu_groups
                gpu_group, gpu_group_devices = find_gpu_iommu_group(
                    system_info["gpu_for_passthrough"], 
                    iommu_groups
                )
                system_info["gpu_iommu_group"] = gpu_group
                system_info["gpu_group_devices"] = gpu_group_devices
                
                if gpu_group_devices:
                    system_info["device_ids"] = get_device_ids(gpu_group_devices)
    
    return system_info


def display_system_summary(system_info):
    """Display a summary of the system information."""
    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    print(f"{Colors.BOLD}{'VFIO Setup - System Summary':^80}{Colors.ENDC}")
    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    
    # Prerequisites status
    print(f"{Colors.BOLD}Prerequisites:{Colors.ENDC}")
    
    if system_info["root_privileges"]:
        print(f"  {Colors.GREEN}✓{Colors.ENDC} Running with root privileges")
    else:
        print(f"  {Colors.RED}✗{Colors.ENDC} Not running with root privileges (required)")
    
    if system_info["cpu_virtualization"]:
        print(f"  {Colors.GREEN}✓{Colors.ENDC} CPU virtualization is enabled")
    else:
        print(f"  {Colors.RED}✗{Colors.ENDC} CPU virtualization is not enabled (required)")
    
    if system_info["iommu_enabled"]:
        print(f"  {Colors.GREEN}✓{Colors.ENDC} IOMMU is enabled")
    else:
        print(f"  {Colors.YELLOW}!{Colors.ENDC} IOMMU is not properly enabled (will be configured)")
    
    if system_info["vfio_modules_loaded"]:
        print(f"  {Colors.GREEN}✓{Colors.ENDC} VFIO modules are loaded")
    else:
        print(f"  {Colors.YELLOW}!{Colors.ENDC} VFIO modules are not loaded (will be configured)")
    
    if system_info.get("gpu_for_passthrough"):
        gpu = system_info["gpu_for_passthrough"]
        print(f"  {Colors.GREEN}✓{Colors.ENDC} GPU for passthrough: {gpu['description']} at {gpu['bdf']}")
    else:
        print(f"  {Colors.RED}✗{Colors.ENDC} No suitable GPU for passthrough found (required)")
    
    if system_info.get("gpu_iommu_group"):
        print(f"  {Colors.GREEN}✓{Colors.ENDC} GPU is in IOMMU group {system_info['gpu_iommu_group']}")
    elif system_info.get("gpu_for_passthrough"):
        print(f"  {Colors.RED}✗{Colors.ENDC} Could not determine GPU IOMMU group (required)")
    
    if system_info["libvirt_installed"]:
        print(f"  {Colors.GREEN}✓{Colors.ENDC} Virtualization software is installed")
    else:
        print(f"  {Colors.YELLOW}!{Colors.ENDC} Virtualization software is not installed (recommended)")
    
    if system_info["btrfs_system"]:
        print(f"  {Colors.BLUE}i{Colors.ENDC} System uses BTRFS filesystem (snapshot recommended)")
    
    # Configuration status
    print(f"\n{Colors.BOLD}Configuration Needed:{Colors.ENDC}")
    
    if not system_info["iommu_enabled"]:
        print(f"  {Colors.YELLOW}→{Colors.ENDC} Configure kernel parameters for IOMMU")
    
    if not system_info["vfio_modules_loaded"] or system_info.get("device_ids"):
        print(f"  {Colors.YELLOW}→{Colors.ENDC} Configure VFIO modules for GPU passthrough")
    
    if not system_info["libvirt_installed"]:
        print(f"  {Colors.YELLOW}→{Colors.ENDC} Install virtualization software")
    
    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")


def interactive_setup(system_info, dry_run=False, debug=False):
    """Run the setup process interactively."""
    changes = {}
    
    if not system_info["root_privileges"]:
        log_error("This script must be run as root (with sudo).")
        return False
    
    if not system_info["cpu_virtualization"]:
        log_error("CPU virtualization is not enabled. Please enable it in your BIOS.")
        return False
    
    if not system_info.get("gpu_for_passthrough"):
        log_error("No suitable GPU for passthrough found.")
        return False
    
    if not system_info.get("gpu_iommu_group"):
        log_error("Could not determine GPU IOMMU group. IOMMU might not be properly enabled.")
        return False
    
    # Check if BTRFS is used and recommend snapshot
    if system_info["btrfs_system"]:
        try:
            snapshot_path = create_btrfs_snapshot_recommendation(dry_run, debug)
            if snapshot_path:
                changes = track_change(changes, "btrfs", snapshot_path, "snapshot created")
        except Exception as e:
            log_error(f"Error during snapshot creation: {str(e)}")
            log_warning("Continuing setup without snapshot creation.")
    
    # Configure IOMMU if needed
    if not system_info["iommu_enabled"]:
        print(f"\n{Colors.BOLD}IOMMU Configuration{Colors.ENDC}")
        response = input("IOMMU is not properly enabled. Configure kernel parameters? (y/n): ").lower()
        if response == 'y':
            # Backup grub file before modification
            grub_path = '/etc/default/grub'
            if os.path.exists(grub_path) and not dry_run:
                shutil.copy2(grub_path, f"{grub_path}.bak")
                changes = track_change(changes, "files", grub_path, "modified")
            elif dry_run:
                log_debug(f"Would backup {grub_path} to {grub_path}.bak", debug)
                changes = track_change(changes, "files", grub_path, "modified")
            
            if configure_kernel_parameters(dry_run, debug):
                changes = track_change(changes, "grub", "updated", "IOMMU parameters added")
                log_success("Kernel parameters configured successfully.")
            else:
                log_error("Failed to configure kernel parameters.")
    
    # Configure VFIO modules
    if system_info.get("device_ids"):
        print(f"\n{Colors.BOLD}VFIO Module Configuration{Colors.ENDC}")
        response = input("Configure VFIO modules for GPU passthrough? (y/n): ").lower()
        if response == 'y':
            # Track files that will be modified
            vfio_conf = '/etc/modprobe.d/vfio.conf'
            if os.path.exists(vfio_conf) and not dry_run:
                shutil.copy2(vfio_conf, f"{vfio_conf}.bak")
                changes = track_change(changes, "files", vfio_conf, "modified")
            elif dry_run and os.path.exists(vfio_conf):
                log_debug(f"Would backup {vfio_conf} to {vfio_conf}.bak", debug)
                changes = track_change(changes, "files", vfio_conf, "modified")
            else:
                changes = track_change(changes, "files", vfio_conf, "created")
            
            modules_load = '/etc/modules-load.d/vfio.conf'
            if os.path.exists(modules_load) and not dry_run:
                shutil.copy2(modules_load, f"{modules_load}.bak")
                changes = track_change(changes, "files", modules_load, "modified")
            elif dry_run and os.path.exists(modules_load):
                log_debug(f"Would backup {modules_load} to {modules_load}.bak", debug)
                changes = track_change(changes, "files", modules_load, "modified")
            else:
                changes = track_change(changes, "files", modules_load, "created")
            
            if configure_vfio_modules(system_info["device_ids"], dry_run, debug):
                changes = track_change(changes, "vfio", "configured", "Device IDs: " + ",".join(system_info["device_ids"]))
                log_success("VFIO modules configured successfully.")
            else:
                log_error("Failed to configure VFIO modules.")
    
    # Update initramfs
    if "vfio" in changes or "grub" in changes:
        print(f"\n{Colors.BOLD}Initramfs Update{Colors.ENDC}")
        response = input("Update initramfs to apply the changes? (y/n): ").lower()
        if response == 'y':
            if update_initramfs(dry_run, debug):
                changes = track_change(changes, "initramfs", "updated", "VFIO modules included")
                log_success("Initramfs updated successfully.")
            else:
                log_error("Failed to update initramfs.")
    
    # Install virtualization software if needed
    if not system_info["libvirt_installed"]:
        print(f"\n{Colors.BOLD}Virtualization Software{Colors.ENDC}")
        response = input("Would you like to install virtualization software? (y/n): ").lower()
        if response == 'y':
            install_cmd = ""
            if shutil.which("apt-get"):
                install_cmd = "apt-get install -y libvirt-daemon qemu-kvm virt-manager"
            elif shutil.which("dnf"):
                install_cmd = "dnf install -y libvirt qemu-kvm virt-manager"
            elif shutil.which("pacman"):
                install_cmd = "pacman -S libvirt qemu virt-manager"
            
            if install_cmd:
                if dry_run:
                    log_debug(f"Would install virtualization software with: {install_cmd}", debug)
                    log_success("[DRY RUN] Virtualization software would be installed")
                    changes = track_change(changes, "packages", "virtualization", "installed")
                else:
                    log_info(f"Installing virtualization software with: {install_cmd}")
                    result = run_command(install_cmd)
                    if result:
                        changes = track_change(changes, "packages", "virtualization", "installed")
                        log_success("Virtualization software installed successfully.")
                    else:
                        log_error("Failed to install virtualization software.")
            else:
                log_warning("Could not determine package manager for installation.")
                log_info("Please install libvirt, qemu-kvm, and virt-manager manually.")
    
    # Create cleanup script
    if changes:
        try:
            log_info("Creating a cleanup script to revert changes if needed...")
            cleanup_script = create_cleanup_script(changes, dry_run, debug)
            
            # Save the changes to a JSON file for reference
            changes_file = "/home/xiao/Documents/source/repo/vfio/vfio_changes.json"
            
            if dry_run:
                log_debug(f"Would write changes to {changes_file}", debug)
                log_debug(f"Changes content: {json.dumps(changes, indent=2)}", debug)
                log_success("[DRY RUN] Changes would be tracked for later cleanup")
            else:
                with open(changes_file, 'w') as f:
                    json.dump(changes, f, indent=2)
                
                log_success(f"Changes have been tracked in {changes_file}")
        except Exception as e:
            log_error(f"Error creating cleanup information: {str(e)}")
            log_warning("You may need to manually revert changes if needed.")
    
    return True


def verify_setup(system_info, dry_run=False):
    """Verify the setup after changes."""
    log_info("Verifying VFIO setup...")
    
    if dry_run:
        log_info("[DRY RUN] In a real run, this would verify the actual changes")
        print(f"\n{Colors.BOLD}Setup Verification (Simulated):{Colors.ENDC}")
        print(f"  {Colors.YELLOW}!{Colors.ENDC} IOMMU status would be checked after changes")
        print(f"  {Colors.YELLOW}!{Colors.ENDC} VFIO modules would be checked after changes")
        print(f"  {Colors.YELLOW}!{Colors.ENDC} Virtualization software would be checked after changes")
        print(f"\n{Colors.YELLOW}{Colors.BOLD}A system reboot would be required for all changes to take effect.{Colors.ENDC}")
        return True
    
    updated_info = gather_system_info()
    
    print(f"\n{Colors.BOLD}Setup Verification:{Colors.ENDC}")
    
    if updated_info["iommu_enabled"]:
        print(f"  {Colors.GREEN}✓{Colors.ENDC} IOMMU is properly enabled")
    else:
        print(f"  {Colors.YELLOW}!{Colors.ENDC} IOMMU is still not properly enabled (reboot required)")
    
    if updated_info["vfio_modules_loaded"]:
        print(f"  {Colors.GREEN}✓{Colors.ENDC} VFIO modules are loaded")
    else:
        print(f"  {Colors.YELLOW}!{Colors.ENDC} VFIO modules are still not loaded (reboot required)")
    
    if updated_info["libvirt_installed"]:
        print(f"  {Colors.GREEN}✓{Colors.ENDC} Virtualization software is installed")
    else:
        print(f"  {Colors.YELLOW}!{Colors.ENDC} Virtualization software is not installed")
    
    # Check if a reboot is needed
    if (not system_info["iommu_enabled"] and not updated_info["iommu_enabled"]) or \
       (not system_info["vfio_modules_loaded"] and not updated_info["vfio_modules_loaded"]):
        print(f"\n{Colors.YELLOW}{Colors.BOLD}A system reboot is required for all changes to take effect.{Colors.ENDC}")
    
    return True


def main():
    """Main function to run the VFIO setup."""
    parser = argparse.ArgumentParser(description='VFIO GPU Passthrough Setup Script')
    parser.add_argument('--dry-run', action='store_true', help='Simulate all operations without making actual changes')
    parser.add_argument('--debug', action='store_true', help='Enable verbose debug output')
    parser.add_argument('--cleanup', action='store_true', help='Run cleanup script if it exists')
    args = parser.parse_args()
    
    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    if args.dry_run:
        print(f"{Colors.BOLD}{Colors.YELLOW}{'VFIO GPU Passthrough Setup [DRY RUN MODE]':^80}{Colors.ENDC}")
    else:
        print(f"{Colors.BOLD}{'VFIO GPU Passthrough Setup':^80}{Colors.ENDC}")
    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    
    if args.debug:
        log_debug("Debug mode enabled", True)
        
    if args.dry_run:
        log_warning("Dry run mode: changes will be simulated but not actually made")
    
    # Run cleanup if requested
    if args.cleanup:
        cleanup_script = "/home/xiao/Documents/source/repo/vfio/vfio_cleanup.sh"
        if os.path.exists(cleanup_script):
            if args.dry_run:
                log_debug(f"Would run cleanup script: {cleanup_script}", args.debug)
                log_success("[DRY RUN] Cleanup would be performed")
                return
            
            log_info(f"Running cleanup script: {cleanup_script}")
            result = run_command(f"bash {cleanup_script}", args.dry_run, args.debug)
            if result:
                log_success("Cleanup completed successfully.")
            else:
                log_error("Cleanup failed.")
            return
        else:
            log_error("Cleanup script not found.")
            return
    
    # Check if running as root
    if os.geteuid() != 0:
        log_error("This script must be run as root (with sudo).")
        sys.exit(1)
    
    # Gather all system information
    system_info = gather_system_info()
    
    # Display summary
    display_system_summary(system_info)
    
    # Ask user if they want to proceed
    print()
    if not args.dry_run:
        proceed = input("Do you want to proceed with the VFIO setup? (y/n): ").lower()
        if proceed != 'y':
            log_info("Setup canceled by user.")
            sys.exit(0)
    else:
        print("Since this is a dry run, we'll simulate the setup process.")
    
    # Perform interactive setup
    if interactive_setup(system_info, args.dry_run, args.debug):
        # Verify setup
        verify_setup(system_info, args.dry_run)
        
        print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
        if args.dry_run:
            log_success("[DRY RUN] VFIO GPU passthrough setup simulation complete!")
            log_info("Run without --dry-run to make actual changes.")
        else:
            log_success("VFIO GPU passthrough setup complete!")
            log_info("To revert all changes, run: sudo python3 vfio.py --cleanup")
            log_info("Please reboot your system for the changes to take effect.")
        
        log_info("After reboot, verify that the AMD GPU is bound to the vfio-pci driver with:")
        log_info("  lspci -nnk | grep -A3 'VGA\\|Display'")
        log_info("Then you can use virt-manager to set up a VM with the passed-through GPU.")
        print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    else:
        log_error("VFIO setup failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()