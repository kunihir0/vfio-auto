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


# Get the directory where the script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


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


def check_dependencies():
    """Check if all required commands are available."""
    log_info("Checking for required dependencies...")
    
    required_commands = [
        "lspci", "grep", "awk", "find", "mkdir", "cp", "chmod",
        "cat", "ls", "df", "test"
    ]
    
    # Check for bootloader/initramfs update commands
    # We don't require all of them, just the ones appropriate for the system
    update_commands = {
        "grub": ["update-grub", "grub-mkconfig", "grub2-mkconfig"],
        "initramfs": ["update-initramfs", "dracut"]
    }
    
    missing_commands = []
    for cmd in required_commands:
        if not shutil.which(cmd):
            missing_commands.append(cmd)
    
    if missing_commands:
        log_error(f"Missing required commands: {', '.join(missing_commands)}")
        log_error("Please install these dependencies before running the script.")
        return False
    
    # Check for at least one update command from each category
    for category, cmds in update_commands.items():
        if not any(shutil.which(cmd) for cmd in cmds):
            log_warning(f"Missing {category} update command. The script may not work correctly.")
            log_warning(f"Required at least one of: {', '.join(cmds)}")
    
    log_success("All required dependencies are available.")
    return True


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


def check_cpu_vendor():
    """Check if the CPU is from AMD."""
    log_info("Checking CPU vendor...")
    
    vendor_id = run_command("grep -m1 'vendor_id' /proc/cpuinfo | awk '{print $3}'")
    
    if vendor_id == "AuthenticAMD":
        log_success("CPU vendor is AMD.")
        return True
    else:
        log_error(f"CPU vendor is {vendor_id}, but this script is tailored for AMD systems.")
        log_error("The script may not work correctly with your CPU.")
        return False


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
    
    # Check if IOMMU is enabled at all
    iommu_enabled = "amd_iommu=on" in cmdline or "intel_iommu=on" in cmdline
    
    # Check if IOMMU is in passthrough mode
    iommu_pt = "iommu=pt" in cmdline
    
    if iommu_enabled and iommu_pt:
        log_success("IOMMU is properly enabled in passthrough mode.")
        return True
    elif iommu_enabled:
        log_warning("IOMMU is enabled, but not in passthrough mode (iommu=pt).")
        log_warning("Passthrough mode is recommended for optimal performance.")
        return False
    else:
        log_warning("IOMMU is not enabled in kernel parameters.")
        return False


def check_kernel_cmdline_conflicts():
    """Check for VFIO device IDs on the kernel command line."""
    log_info("Checking for VFIO configuration in kernel command line...")
    
    cmdline = Path("/proc/cmdline").read_text()
    
    # Check for VFIO device IDs on the kernel command line
    vfio_ids_pattern = re.search(r'vfio-pci\.ids=([^\s]+)', cmdline)
    
    if vfio_ids_pattern:
        vfio_ids = vfio_ids_pattern.group(1)
        log_warning("VFIO device IDs are specified on the kernel command line:")
        log_warning(f"  vfio-pci.ids={vfio_ids}")
        log_warning("This script will set up VFIO via /etc/modprobe.d/vfio.conf, which is generally preferred.")
        log_warning("Having both configurations may lead to unexpected behavior.")
        return True
    
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
    nvidia_gpus = [gpu for gpu in gpus if gpu['vendor'] == 'NVIDIA']
    
    if not amd_gpus:
        log_error("No AMD GPUs found for passthrough.")
        return None
    
    if not nvidia_gpus and not [gpu for gpu in gpus if gpu['vendor'] != 'AMD']:
        log_warning("No non-AMD GPUs found. Make sure you have a GPU for the host system.")
    
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
    
    # Add warning about IOMMU group implications
    log_warning("All devices in this IOMMU group will be bound to vfio-pci driver")
    log_warning("This means they will be unavailable to the host system")
    log_warning("If this group contains devices other than the GPU and its audio controller,")
    log_warning("you may need to pass them through to your VM as well")
    
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


def create_timestamped_backup(file_path, dry_run=False, debug=False):
    """Create a timestamped backup of a file."""
    if not os.path.exists(file_path):
        log_debug(f"File {file_path} does not exist, no backup needed", debug)
        return None
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = f"{file_path}.bak.{timestamp}"
    
    if dry_run:
        log_debug(f"Would create backup of {file_path} to {backup_path}", debug)
        return backup_path
    
    try:
        shutil.copy2(file_path, backup_path)
        log_info(f"Created backup of {file_path} to {backup_path}")
        return backup_path
    except Exception as e:
        log_error(f"Failed to create backup of {file_path}: {str(e)}")
        return None


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


def detect_bootloader():
    """Detect the bootloader used by the system."""
    # Check for GRUB
    if os.path.exists('/etc/default/grub'):
        if os.path.exists('/usr/sbin/update-grub'):
            return "grub-debian"  # Debian/Ubuntu style
        elif os.path.exists('/usr/sbin/grub2-mkconfig'):
            return "grub-fedora"  # Fedora/RHEL style
        elif os.path.exists('/usr/sbin/grub-mkconfig'):
            return "grub-arch"    # Arch style
        else:
            return "grub-unknown"
    
    # Check for systemd-boot
    if os.path.exists('/boot/efi/loader/loader.conf') or os.path.exists('/boot/loader/loader.conf'):
        return "systemd-boot"
    
    # Check for LILO
    if os.path.exists('/etc/lilo.conf'):
        return "lilo"
    
    return "unknown"


def configure_kernel_parameters(dry_run=False, debug=False):
    """Configure kernel parameters for IOMMU and VFIO."""
    log_info("Configuring kernel parameters...")
    
    # Detect bootloader
    bootloader = detect_bootloader()
    log_info(f"Detected bootloader: {bootloader}")
    
    if "grub" not in bootloader:
        log_warning(f"This script primarily supports GRUB bootloader. Detected: {bootloader}")
        log_warning("You may need to manually configure your bootloader with these parameters:")
        log_warning("  amd_iommu=on iommu=pt rd.driver.pre=vfio-pci")
        
        # For systemd-boot, provide additional guidance
        if bootloader == "systemd-boot":
            log_info("For systemd-boot, you need to edit/create entries in /boot/loader/entries/")
            log_info("Add the kernel parameters to the 'options' line in your entry file.")
        
        response = input("Continue anyway? (y/n): ").lower()
        if response != 'y':
            return False
    
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
    
    # Determine appropriate IOMMU parameter based on CPU vendor
    is_amd = check_cpu_vendor()
    
    # Add required parameters if not already present
    required_params = [
        "amd_iommu=on" if is_amd else "intel_iommu=on",  # Choose based on CPU vendor
        "iommu=pt",      # IOMMU passthrough mode (most efficient for VM passthrough)
        "rd.driver.pre=vfio-pci",  # Force vfio-pci to load very early in initramfs
        # Note: rd.driver.pre=vfio-pci is generally needed for proper GPU passthrough,
        # but some modern dracut configurations might handle this automatically
    ]
    
    # Ask for advanced parameters if in debug mode
    if debug:
        print("\nAdvanced IOMMU configuration options:")
        print("1. iommu=pt (passthrough mode, recommended for best performance)")
        print("2. iommu=on (default mode, may be more compatible with some systems)")
        advanced_choice = input("Choose IOMMU mode (1/2) [default=1]: ")
        
        if advanced_choice == "2":
            # Replace iommu=pt with iommu=on in required params
            required_params = [p if not p.startswith("iommu=") else "iommu=on" for p in required_params]
    
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
    
    # Create the final parameter string for display/non-GRUB users
    final_params_string = " ".join(parameters)
    
    # For non-GRUB bootloaders, provide the exact string to copy-paste
    if "grub" not in bootloader:
        log_info(f"The required kernel options line is: {final_params_string}")
    
    if dry_run:
        log_debug(f"Would update GRUB configuration in {grub_path}", debug)
        log_debug(f"New parameters: {params_to_add}", debug)
        log_debug(f"New GRUB_CMDLINE_LINUX_DEFAULT value: {final_params_string}", debug)
        
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
    backup_path = create_timestamped_backup(grub_path, dry_run, debug)
    if not backup_path and not dry_run:
        log_error("Failed to create backup, aborting GRUB configuration update for safety")
        return False
    
    # Update the GRUB configuration
    grub_content[cmdline_line_index] = f'GRUB_CMDLINE_LINUX_DEFAULT="{final_params_string}"\n'
    
    try:
        with open(grub_path, 'w') as f:
            f.writelines(grub_content)
    except Exception as e:
        log_error(f"Failed to update GRUB configuration: {str(e)}")
        log_error(f"You can restore from the backup: {backup_path}")
        return False
    
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
        log_error(f"You can restore from the backup: {backup_path}")
        log_error("After restoring, manually update your bootloader configuration.")
        return False


def update_initramfs(dry_run=False, debug=False):
    """Update the initramfs to include VFIO modules."""
    log_info("Updating initramfs...")
    
    # Check for space in /boot
    boot_space_output = run_command("df -h /boot", dry_run, debug)
    if boot_space_output:
        usage_match = re.search(r"(\d+)%", boot_space_output)
        if usage_match and int(usage_match.group(1)) > 90:
            log_warning("Warning: /boot partition is over 90% full!")
            log_warning("The initramfs update might fail due to insufficient space.")
            log_warning("Consider cleaning up old kernels before proceeding.")
            response = input("Continue anyway? (y/n): ").lower()
            if response != 'y':
                return False
    
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
        log_error("Your system may not boot properly until this is resolved.")
        log_error("Please check /boot partition space and permissions, then manually run:")
        log_error(f"  sudo {initramfs_command}")
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
    
    script_path = os.path.join(SCRIPT_DIR, "vfio_cleanup.sh")
    script_content = "#!/bin/bash\n\n"
    script_content += "# VFIO Cleanup Script\n"
    script_content += "# This script will revert the changes made by the VFIO setup script\n\n"
    script_content += "# Exit on error\nset -e\n\n"
    script_content += "echo 'Starting VFIO cleanup...'\n\n"
    
    # Handle files created or modified
    if "files" in changes:
        script_content += "# Reverting file changes\n"
        for change in changes["files"]:
            # Find the most recent backup before our changes
            if change["content"] == "created":
                script_content += f"if [ -f '{change['item']}' ]; then\n"
                script_content += f"  echo 'Removing file {change['item']}'\n"
                script_content += f"  rm -f '{change['item']}'\n"
                script_content += "else\n"
                script_content += f"  echo 'File {change['item']} already removed'\n"
                script_content += "fi\n\n"
            elif change["content"] == "modified":
                # Find the most recent backup
                if "backup_path" in change:
                    backup_path = change["backup_path"]
                    script_content += f"if [ -f '{backup_path}' ]; then\n"
                    script_content += f"  if [ -f '{change['item']}' ]; then\n"
                    script_content += f"    echo 'Checking if {change['item']} needs restoration...'\n"
                    script_content += f"    if ! cmp -s '{change['item']}' '{backup_path}'; then\n"
                    script_content += f"      echo 'Restoring {change['item']} from {backup_path}'\n"
                    script_content += f"      cp -pf '{backup_path}' '{change['item']}'\n"
                    script_content += "    else\n"
                    script_content += f"      echo 'No restoration needed for {change['item']}'\n"
                    script_content += "    fi\n"
                    script_content += "  else\n"
                    script_content += f"    echo 'File {change['item']} not found, restoring from backup'\n"
                    script_content += f"    cp -pf '{backup_path}' '{change['item']}'\n"
                    script_content += "  fi\n"
                    script_content += "else\n"
                    script_content += f"  echo 'Warning: Backup {backup_path} not found, cannot restore {change['item']}'\n"
                    script_content += "fi\n\n"
    
    # Handle initramfs updates
    if "initramfs" in changes:
        script_content += "# Updating initramfs after reverting changes\n"
        script_content += "echo 'Updating initramfs...'\n"
        if os.path.exists('/usr/sbin/update-initramfs'):
            script_content += "if ! update-initramfs -u -k all; then\n"
            script_content += "  echo 'Failed to update initramfs. Please update manually.'\n"
            script_content += "  exit 1\n"
            script_content += "fi\n\n"
        elif os.path.exists('/usr/bin/dracut'):
            script_content += "if ! dracut --force --regenerate-all; then\n"
            script_content += "  echo 'Failed to update initramfs. Please update manually.'\n"
            script_content += "  exit 1\n"
            script_content += "fi\n\n"
    
    # Handle GRUB updates
    if "grub" in changes:
        script_content += "# Updating GRUB after reverting changes\n"
        script_content += "echo 'Updating bootloader configuration...'\n"
        if os.path.exists('/usr/sbin/update-grub'):
            script_content += "if ! update-grub; then\n"
            script_content += "  echo 'Failed to update GRUB. Please update manually.'\n"
            script_content += "  exit 1\n"
            script_content += "fi\n\n"
        elif os.path.exists('/usr/sbin/grub2-mkconfig'):
            script_content += "if ! grub2-mkconfig -o /boot/grub2/grub.cfg; then\n"
            script_content += "  echo 'Failed to update GRUB. Please update manually.'\n"
            script_content += "  exit 1\n"
            script_content += "fi\n\n"
        elif os.path.exists('/usr/sbin/grub-mkconfig'):
            if os.path.exists('/boot/grub/grub.cfg'):
                script_content += "if ! grub-mkconfig -o /boot/grub/grub.cfg; then\n"
                script_content += "  echo 'Failed to update GRUB. Please update manually.'\n"
                script_content += "  exit 1\n"
                script_content += "fi\n\n"
            elif os.path.exists('/boot/grub2/grub.cfg'):
                script_content += "if ! grub-mkconfig -o /boot/grub2/grub.cfg; then\n"
                script_content += "  echo 'Failed to update GRUB. Please update manually.'\n"
                script_content += "  exit 1\n"
                script_content += "fi\n\n"
    
    # Handle BTRFS snapshot
    if "btrfs" in changes:
        script_content += "# Note about BTRFS snapshot\n"
        for change in changes["btrfs"]:
            script_content += f"if [ -d '{change['item']}' ]; then\n"
            script_content += f"  echo 'A BTRFS snapshot was created at {change['item']}'\n"
            script_content += "  echo 'You can manually restore from this snapshot with:'\n"
            script_content += f"  echo \"  sudo btrfs subvolume snapshot {change['item']} /\"\n"
            script_content += "  echo 'Or delete it with:'\n"
            script_content += f"  echo \"  sudo btrfs subvolume delete {change['item']}\"\n"
            script_content += "else\n"
            script_content += f"  echo 'BTRFS snapshot at {change['item']} no longer exists'\n"
            script_content += "fi\n\n"
    
    # Add note about package installations
    script_content += "# Note about package installations\n"
    script_content += "echo \"\"\n"
    script_content += "echo \"Note: If virtualization software (libvirt, qemu, virt-manager) was installed,\"\n"
    script_content += "echo \"this cleanup script does not automatically remove it. You may need to\"\n"
    script_content += "echo \"uninstall these packages manually if desired.\"\n"
    script_content += "echo \"\"\n"
    
    script_content += "echo 'VFIO cleanup complete. Please reboot your system for changes to take effect.'\n"
    
    if dry_run:
        log_debug(f"Would create cleanup script at {script_path}", debug)
        log_debug("Script content:", debug)
        if debug:
            for line in script_content.split('\n'):
                log_debug(f"  {line}", debug)
        
        log_success("[DRY RUN] Cleanup script would be created")
        return script_path
    
    try:
        with open(script_path, "w") as f:
            f.write(script_content)
        
        os.chmod(script_path, 0o755)
        log_success(f"Cleanup script created: {script_path}")
        log_info(f"You can run this script to revert all changes made by the VFIO setup.")
        
        return script_path
    except Exception as e:
        log_error(f"Failed to create cleanup script: {str(e)}")
        return None


def gather_system_info():
    """Gather all relevant information about the system."""
    log_info("Gathering system information...")
    
    system_info = {
        "root_privileges": os.geteuid() == 0,
        "cpu_vendor": check_cpu_vendor(),
        "cpu_virtualization": check_cpu_virtualization(),
        "iommu_enabled": check_iommu(),
        "vfio_modules_loaded": check_vfio_modules(),
        "btrfs_system": check_btrfs(),
        "gpus": get_gpus(),
        "libvirt_installed": check_libvirt_installed(),
        "kernel_cmdline_conflicts": check_kernel_cmdline_conflicts()
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
        
        # Add IOMMU group implications
        if system_info.get("gpu_group_devices") and len(system_info["gpu_group_devices"]) > 1:
            print(f"  {Colors.YELLOW}!{Colors.ENDC} This group has multiple devices that will ALL be unavailable to the host")
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
            backup_path = None
            
            if os.path.exists(grub_path):
                backup_path = create_timestamped_backup(grub_path, dry_run, debug)
                if backup_path:
                    changes = track_change(changes, "files", grub_path, "modified")
                    # Store backup path for cleanup
                    if "files" in changes and any(c["item"] == grub_path for c in changes["files"]):
                        for c in changes["files"]:
                            if c["item"] == grub_path:
                                c["backup_path"] = backup_path
                                break
            
            if configure_kernel_parameters(dry_run, debug):
                changes = track_change(changes, "grub", "updated", "IOMMU parameters added")
                log_success("Kernel parameters configured successfully.")
            else:
                log_error("Failed to configure kernel parameters.")
                log_error("Cannot continue without proper IOMMU configuration.")
                return False
    
    # Configure VFIO modules
    if system_info.get("device_ids"):
        print(f"\n{Colors.BOLD}VFIO Module Configuration{Colors.ENDC}")
        response = input("Configure VFIO modules for GPU passthrough? (y/n): ").lower()
        if response == 'y':
            # Track files that will be modified
            vfio_conf = '/etc/modprobe.d/vfio.conf'
            if os.path.exists(vfio_conf):
                backup_path = create_timestamped_backup(vfio_conf, dry_run, debug)
                if backup_path:
                    changes = track_change(changes, "files", vfio_conf, "modified")
                    # Store backup path for cleanup
                    if "files" in changes and any(c["item"] == vfio_conf for c in changes["files"]):
                        for c in changes["files"]:
                            if c["item"] == vfio_conf:
                                c["backup_path"] = backup_path
                                break
            else:
                changes = track_change(changes, "files", vfio_conf, "created")
            
            modules_load = '/etc/modules-load.d/vfio.conf'
            if os.path.exists(modules_load):
                backup_path = create_timestamped_backup(modules_load, dry_run, debug)
                if backup_path:
                    changes = track_change(changes, "files", modules_load, "modified")
                    # Store backup path for cleanup
                    if "files" in changes and any(c["item"] == modules_load for c in changes["files"]):
                        for c in changes["files"]:
                            if c["item"] == modules_load:
                                c["backup_path"] = backup_path
                                break
            else:
                changes = track_change(changes, "files", modules_load, "created")
            
            if configure_vfio_modules(system_info["device_ids"], dry_run, debug):
                changes = track_change(changes, "vfio", "configured", "Device IDs: " + ",".join(system_info["device_ids"]))
                log_success("VFIO modules configured successfully.")
            else:
                log_error("Failed to configure VFIO modules.")
                log_error("Cannot continue without proper VFIO configuration.")
                return False
    
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
                log_error("Your system may not boot properly. Please resolve the issue.")
                return False
    
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
                        log_warning("You will need to install it manually to use VFIO passthrough.")
            else:
                log_warning("Could not determine package manager for installation.")
                log_info("Please install libvirt, qemu-kvm, and virt-manager manually.")
    
    # Create cleanup script
    if changes:
        try:
            log_info("Creating a cleanup script to revert changes if needed...")
            cleanup_script = create_cleanup_script(changes, dry_run, debug)
            
            # Save the changes to a JSON file for reference
            changes_file = os.path.join(SCRIPT_DIR, "vfio_changes.json")
            
            if dry_run:
                log_debug(f"Would write changes to {changes_file}", debug)
                log_debug(f"Changes content: {json.dumps(changes, indent=2)}", debug)
                log_success("[DRY RUN] Changes would be tracked for later cleanup")
            else:
                try:
                    with open(changes_file, 'w') as f:
                        json.dump(changes, f, indent=2)
                    
                    log_success(f"Changes have been tracked in {changes_file}")
                except Exception as e:
                    log_error(f"Failed to save changes to {changes_file}: {str(e)}")
                    log_warning("Cleanup script may not be able to restore all changes.")
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
    parser.add_argument('--output-dir', type=str, default=SCRIPT_DIR, 
                        help='Directory to store output files (cleanup script, changes log)')
    args = parser.parse_args()
    
    # Update script dir if output-dir is specified
    global SCRIPT_DIR
    if args.output_dir != SCRIPT_DIR:
        if os.path.isdir(args.output_dir):
            SCRIPT_DIR = args.output_dir
            log_info(f"Using output directory: {SCRIPT_DIR}")
        else:
            log_error(f"Output directory {args.output_dir} does not exist")
            return 1
    
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
    
    # Check dependencies first
    if not check_dependencies():
        log_error("Missing required dependencies. Please install them and try again.")
        return 1
    
    # Run cleanup if requested
    if args.cleanup:
        cleanup_script = os.path.join(SCRIPT_DIR, "vfio_cleanup.sh")
        if os.path.exists(cleanup_script):
            if args.dry_run:
                log_debug(f"Would run cleanup script: {cleanup_script}", args.debug)
                log_success("[DRY RUN] Cleanup would be performed")
                return 0
            
            log_info(f"Running cleanup script: {cleanup_script}")
            result = run_command(f"bash {cleanup_script}", args.dry_run, args.debug)
            if result:
                log_success("Cleanup completed successfully.")
            else:
                log_error("Cleanup failed.")
            return 0
        else:
            log_error(f"Cleanup script not found at {cleanup_script}")
            return 1
    
    # Check if running as root
    if os.geteuid() != 0:
        log_error("This script must be run as root (with sudo).")
        return 1
    
    # Check if CPU is AMD
    if not check_cpu_vendor():
        log_warning("This script is designed for AMD CPUs. Proceed with caution.")
        proceed = input("Continue anyway? (y/n): ").lower()
        if proceed != 'y':
            log_info("Setup canceled due to CPU vendor mismatch.")
            return 0
    
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
            return 0
    else:
        print("Since this is a dry run, we'll simulate the setup process.")
    
    # Perform interactive setup
    if interactive_setup(system_info, args.dry_run, args.debug):
        # Verify setup
        verify_setup(system_info, args.dry_run)
        
        # Get the definite path to the cleanup script
        cleanup_script_path = os.path.join(SCRIPT_DIR, "vfio_cleanup.sh")
        
        print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
        if args.dry_run:
            log_success("[DRY RUN] VFIO GPU passthrough setup simulation complete!")
            log_info("Run without --dry-run to make actual changes.")
        else:
            log_success("VFIO GPU passthrough setup complete!")
            log_info(f"To revert all changes, you can run the generated cleanup script:")
            log_info(f"  sudo bash {cleanup_script_path}")
            log_info(f"(Alternatively, run: sudo python3 {os.path.basename(__file__)} --cleanup --output-dir '{SCRIPT_DIR}')")
            log_info("Please reboot your system for the changes to take effect.")
        
        log_info("After reboot, verify that the AMD GPU is bound to the vfio-pci driver with:")
        log_info("  lspci -nnk | grep -A3 'VGA\\|Display'")
        log_info("Then you can use virt-manager to set up a VM with the passed-through GPU.")
        print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
        return 0
    else:
        log_error("VFIO setup failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())