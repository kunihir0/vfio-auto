"""System checks for VFIO passthrough prerequisites."""

import os
import re
import shutil
from pathlib import Path
from typing import Optional, Tuple

from .utils import (
    log_info, log_success, log_warning, log_error, log_debug,
    cached_result, run_command
)
from .bootloader import get_kernel_cmdline


def check_root() -> bool:
    """Check if the script is running with root privileges."""
    is_root = os.geteuid() == 0
    if not is_root:
        log_error("This script must be run as root (with sudo).")
    else:
        log_success("Running with root privileges.")
    return is_root


def check_dependencies(debug: bool = False) -> bool:
    """Check if all required commands are available."""
    log_info("Checking for required dependencies...")

    required_commands = [
        "lspci", "grep", "awk", "find", "mkdir", "cp", "chmod",
        "cat", "ls", "df", "test", "uname", "sed", "cmp",  # Added sed, cmp for grub default editing and cleanup
        "dmesg",  # Added for post-reboot check info
        "id",  # Added for cleanup script root check
        "bash",  # Added for cleanup script execution
    ]

    # Check for bootloader/initramfs update commands based on the actual bootloader
    from .bootloader import detect_bootloader
    bootloader = detect_bootloader()
    update_commands = {
        "grub-debian": ["update-grub"],
        "grub-fedora": ["grub2-mkconfig"],
        "grub-arch": ["grub-mkconfig"],
        "systemd-boot": [],  # No special commands needed for systemd-boot base
        "systemd-boot-popos": ["kernelstub"],  # Pop!_OS uses kernelstub
        "lilo": ["lilo"],
        "unknown": ["update-grub", "grub-mkconfig", "grub2-mkconfig", "kernelstub"]  # Check all common ones
    }

    # Add initramfs commands based on possible systems
    initramfs_cmds = []
    if shutil.which('update-initramfs'):
        initramfs_cmds.append('update-initramfs')
    if shutil.which('dracut'):
        initramfs_cmds.append('dracut')
    if shutil.which('mkinitcpio'):
        initramfs_cmds.append('mkinitcpio')

    missing_commands = []
    for cmd in required_commands:
        if not shutil.which(cmd):
            missing_commands.append(cmd)

    if missing_commands:
        log_error(f"Missing required commands: {', '.join(missing_commands)}")
        log_error("Please install these dependencies before running the script.")
        return False

    # Check for necessary bootloader commands
    bootloader_cmds_needed = update_commands.get(bootloader, [])
    if bootloader_cmds_needed and not any(shutil.which(cmd) for cmd in bootloader_cmds_needed):
        # If unknown, check against the 'unknown' list
        if bootloader == "unknown":
            unknown_cmds_to_check = update_commands["unknown"]
            if not any(shutil.which(cmd) for cmd in unknown_cmds_to_check):
                log_warning(f"Could not detect bootloader, and missing common update commands.")
                log_warning(f"Looked for: {', '.join(unknown_cmds_to_check)}")
            # If at least one unknown command exists, maybe it's okay
        else:
            log_warning(f"Missing bootloader update command for {bootloader}.")
            log_warning(f"Required one of: {', '.join(bootloader_cmds_needed)}")

    # Check for necessary initramfs commands
    if not initramfs_cmds:
        log_warning(f"Missing initramfs update command (update-initramfs, dracut, or mkinitcpio).")
    else:
        log_debug(f"Found initramfs command(s): {', '.join(initramfs_cmds)}", debug)

    log_success("All required dependencies are available.")
    return True


@cached_result('cpu_vendor_str')
def get_cpu_vendor_str() -> str:
    """Gets the CPU vendor string."""
    vendor_id = run_command("grep -m1 'vendor_id' /proc/cpuinfo | awk '{print $3}'")
    return vendor_id or "Unknown"


@cached_result('is_amd_cpu')
def is_amd_cpu() -> bool:
    """Check if the CPU is from AMD."""
    log_info("Checking CPU vendor...")
    vendor_id = get_cpu_vendor_str()
    if vendor_id == "AuthenticAMD":
        log_success("CPU vendor is AMD.")
        return True
    else:
        log_error(f"CPU vendor is {vendor_id}, not AMD.")
        log_warning("This script is primarily designed for AMD systems.")
        return False


def check_cpu_virtualization(debug: bool = False) -> bool:
    """Check if CPU virtualization is enabled."""
    log_info("Checking CPU virtualization...")
    vendor_id = get_cpu_vendor_str()
    is_amd = vendor_id == "AuthenticAMD"

    # Check for AMD-V (svm) or Intel VT-x (vmx)
    output = run_command("grep -m1 -E -o 'svm|vmx' /proc/cpuinfo", debug=debug)
    log_debug(f"Raw virtualization check output from run_command: '{output}'", debug)

    if output is not None:
        # Clean and get first instance of the flag
        output_clean = output.strip().split('\n')[0]
        log_debug(f"Cleaned virtualization check output: '{output_clean}'", debug)
        if output_clean == "svm" and is_amd:
            log_success("AMD-V (svm) virtualization is available.")
            return True
        elif output_clean == "vmx" and not is_amd:
            log_success("Intel VT-x (vmx) virtualization is available.")
            return True
        # Checks for mismatches
        elif output_clean == "svm" and not is_amd:
            log_error(f"Found 'svm' flag but CPU vendor is '{vendor_id}'. BIOS/CPU reporting inconsistency?")
            return False
        elif output_clean == "vmx" and is_amd:
            log_error(f"Found 'vmx' flag but CPU vendor is 'AuthenticAMD'. BIOS/CPU reporting inconsistency?")
            return False
        else:
            # Flag found but doesn't match vendor expectation
            virt_type = "SVM (AMD-V)" if is_amd else "VT-x (vmx)"
            log_error(f"CPU virtualization flag found ('{output_clean}') but it does not match the expected type ({virt_type}) for vendor '{vendor_id}'.")
            log_error("Possible BIOS/CPU reporting inconsistency or unexpected flag.")
            return False

    # If output is None or fallthrough from mismatch
    virt_type = "SVM (AMD-V)" if is_amd else "VT-x (vmx)"
    log_error(f"CPU virtualization ({virt_type}) not found or check failed.")  # Updated error message
    if output is None:
        log_error("Could not retrieve virtualization flag from /proc/cpuinfo (command failed).")
    # The case where output was not None but didn't match is handled above
    log_error("Please ensure virtualization is enabled in your system BIOS/UEFI.")
    return False


def check_secure_boot(debug: bool = False) -> Optional[bool]:
    """Check if Secure Boot is enabled."""
    log_info("Checking Secure Boot status...")

    # Check if mokutil is installed
    if shutil.which("mokutil"):
        result = run_command("mokutil --sb-state", debug=debug)
        if result:
            result_lower = result.lower()
            log_debug(f"mokutil --sb-state output: {result_lower}", debug)
            if "secureboot enabled" in result_lower:
                log_warning("Secure Boot is ENABLED via mokutil.")
                log_warning("This might interfere with loading unsigned kernel modules (like vfio-pci).")
                log_warning("Consider disabling Secure Boot or signing your VFIO modules if issues occur.")
                return True
            elif "secureboot disabled" in result_lower:
                log_success("Secure Boot is disabled via mokutil.")
                return False
            else:
                log_warning("Could not determine Secure Boot status from mokutil output.")
        else:
            log_debug("mokutil command failed or produced no output.", debug)

    # Alternative check via EFI variables (less reliable)
    secure_boot_var = Path("/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c")
    if secure_boot_var.exists():
        try:
            # Reading this file requires root and specific capabilities
            # It contains binary data, the last byte indicates status (0=disabled, 1=enabled)
            # Need to read as bytes
            with open(secure_boot_var, "rb") as f:
                data = f.read()
                # The relevant byte is usually the 5th byte (index 4) if UEFI spec compliant
                # However, the actual content can vary. A common pattern is that the last byte matters.
                if len(data) > 0:
                    # Let's check the last byte based on common observations
                    status_byte = data[-1]
                    log_debug(f"Secure Boot EFI var last byte: {status_byte}", debug)
                    if status_byte == 1:
                        log_warning("Secure Boot appears ENABLED via EFI variable.")
                        log_warning("This might interfere with module loading.")
                        return True
                    elif status_byte == 0:
                        log_success("Secure Boot appears disabled via EFI variable.")
                        return False
        except PermissionError:
            log_debug(f"Permission denied reading Secure Boot EFI variable {secure_boot_var}. Requires root/caps.", debug)
        except Exception as e:
            log_warning(f"Could not read Secure Boot status from EFI variable: {e}")

    log_warning("Could not definitively determine Secure Boot status.")
    log_warning("If it is enabled, it might interfere with loading VFIO modules.")
    return None  # Unknown status


@cached_result('iommu_status')
def check_iommu() -> Tuple[bool, bool]:
    """Check if IOMMU is enabled and if passthrough mode is active.

    Returns:
        Tuple[bool, bool]: (iommu_is_generally_enabled, iommu_is_passthrough_mode)
    """
    log_info("Checking IOMMU status in kernel parameters...")
    cmdline = get_kernel_cmdline()

    amd_iommu_on = "amd_iommu=on" in cmdline
    intel_iommu_on = "intel_iommu=on" in cmdline
    iommu_enabled = amd_iommu_on or intel_iommu_on

    iommu_pt = "iommu=pt" in cmdline

    if iommu_enabled and iommu_pt:
        log_success("IOMMU is enabled in kernel parameters (amd/intel_iommu=on) and passthrough mode (iommu=pt) is set.")
    elif iommu_enabled:
        log_warning("IOMMU is enabled in kernel parameters (amd/intel_iommu=on), but passthrough mode (iommu=pt) is NOT set.")
        log_warning("Passthrough mode is recommended for better performance and compatibility.")
    else:
        log_warning("IOMMU does not appear to be enabled in kernel parameters (missing amd_iommu=on or intel_iommu=on).")

    return iommu_enabled, iommu_pt


def check_kernel_cmdline_conflicts(debug: bool = False) -> bool:
    """Check for potentially conflicting VFIO device IDs on the kernel command line."""
    log_info("Checking for VFIO configuration in kernel command line...")
    cmdline = get_kernel_cmdline()
    log_debug(f"Current cmdline: {cmdline}", debug)

    # Check for VFIO device IDs on the kernel command line
    vfio_ids_pattern = re.search(r'vfio-pci\.ids=([^\s]+)', cmdline)

    if vfio_ids_pattern:
        vfio_ids = vfio_ids_pattern.group(1)
        log_warning("VFIO device IDs are specified directly on the kernel command line:")
        log_warning(f"  vfio-pci.ids={vfio_ids}")
        log_warning("This script manages VFIO IDs via /etc/modprobe.d/vfio.conf.")
        log_warning("Having IDs in both places can lead to conflicts or confusion.")
        log_warning("It's recommended to remove vfio-pci.ids from the kernel command line.")
        return True  # Conflict found

    return False  # No conflict found


@cached_result('vfio_modules_loaded')
def check_vfio_modules(debug: bool = False) -> bool:
    """Check if required VFIO modules are loaded."""
    log_info("Checking if VFIO modules are loaded...")
    required_modules = ["vfio", "vfio_iommu_type1", "vfio_pci", "vfio_virqfd"]

    lsmod_output = run_command("lsmod", debug=debug)
    if lsmod_output is None:
        log_error("Failed to run lsmod to check loaded modules.")
        return False  # Cannot determine status

    loaded_modules = set()
    for line in lsmod_output.strip().split('\n')[1:]:  # Skip header
        parts = line.split()
        if parts:
            loaded_modules.add(parts[0])

    log_debug(f"Loaded modules (partial list from lsmod): {list(loaded_modules)[:10]}...", debug)

    missing_modules = [module for module in required_modules if module not in loaded_modules]

    if missing_modules:
        log_warning(f"Required VFIO modules not currently loaded: {', '.join(missing_modules)}")
        log_info("These should be loaded automatically after configuration and reboot.")
        return False
    else:
        log_success("All required VFIO modules appear to be loaded.")
        return True


def check_libvirt_installed(debug: bool = False) -> bool:
    """Check if libvirt is installed for VM management."""
    log_info("Checking for libvirt/QEMU installation...")
    
    # Check for core libvirt/QEMU binaries
    libvirt_found = shutil.which('libvirtd') is not None
    qemu_found = any(shutil.which(f'qemu-system-x86_64{suffix}') is not None 
                    for suffix in ['', '.bin', '.exe', '.static'])
    virsh_found = shutil.which('virsh') is not None
    
    if libvirt_found and qemu_found and virsh_found:
        log_success("Libvirt, QEMU and management tools are installed.")
        return True
    else:
        missing = []
        if not libvirt_found:
            missing.append("libvirtd")
        if not qemu_found:
            missing.append("qemu-system-x86_64")
        if not virsh_found:
            missing.append("virsh")
            
        log_warning(f"Some virtualization components are missing: {', '.join(missing)}")
        log_warning("You may need to install libvirt/QEMU to create VMs with the passthrough GPU.")
        
        # Provide install hints for common distros
        if os.path.exists('/etc/debian_version'):
            log_info("For Debian/Ubuntu, install using: sudo apt install qemu-kvm libvirt-daemon-system")
        elif os.path.exists('/etc/fedora-release'):
            log_info("For Fedora, install using: sudo dnf install @virtualization")
        elif os.path.exists('/etc/arch-release'):
            log_info("For Arch, install using: sudo pacman -S qemu libvirt")
            
        return False