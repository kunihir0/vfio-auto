"""Package installation functionality for VFIO configuration."""

import os
import shutil
from typing import List, Dict, Any, Tuple

from .utils import (
    log_info, log_success, log_warning, log_error, log_debug,
    run_command, get_distro_info
)


def is_arch_based() -> bool:
    """Check if the system is Arch-based."""
    if os.path.exists('/etc/arch-release'):
        return True
    
    distro_info = get_distro_info()
    if distro_info.get('id', '').lower() in ('arch', 'manjaro', 'endeavouros', 'garuda'):
        return True

    return False


def check_package_installed(package_name: str, debug: bool = False) -> bool:
    """Check if a package is installed on an Arch-based system.
    
    Args:
        package_name: Name of the package to check
        debug: If True, print additional debug information
        
    Returns:
        bool: True if the package is installed, False otherwise
    """
    if not is_arch_based():
        log_debug("Not an Arch-based system, skipping package check", debug)
        return False

    # Use pacman to check if package is installed
    cmd = f"pacman -Q {package_name} 2>/dev/null"
    result = run_command(cmd, dry_run=False, debug=debug)
    
    return result is not None


def get_minimal_qemu_packages() -> Dict[str, Dict[str, str]]:
    """Get the minimal set of packages needed for QEMU with TPM, OVMF, and virt-manager.
    
    Returns:
        Dict: Dictionary of package groups and their packages with descriptions
    """
    return {
        "core": {
            "qemu-full": "Complete QEMU installation including all optional components",
            "libvirt": "API for managing virtualization",
            "virt-manager": "GUI for managing virtual machines"
        }
    }


def install_minimal_qemu_packages(dry_run: bool = False, debug: bool = False) -> Tuple[bool, List[str], List[str]]:
    """Install the minimal set of packages needed for QEMU with TPM, OVMF, and virt-manager.
    
    Args:
        dry_run: If True, don't actually install packages
        debug: If True, print additional debug information
        
    Returns:
        Tuple[bool, List[str], List[str]]: (success_status, installed_packages, failed_packages)
    """
    if not is_arch_based():
        log_error("This function is only supported on Arch-based systems.")
        return False, [], []
    
    # Check if pacman is available
    if not shutil.which("pacman"):
        log_error("pacman package manager not found. Cannot install packages.")
        return False, [], []
    
    # Get package groups
    package_groups = get_minimal_qemu_packages()
    
    # Flatten package lists
    all_packages = []
    for group, packages in package_groups.items():
        all_packages.extend(packages.keys())
    
    # Check which packages are already installed
    installed_packages = []
    to_install = []
    for pkg in all_packages:
        if check_package_installed(pkg, debug):
            log_info(f"Package '{pkg}' is already installed.")
            installed_packages.append(pkg)
        else:
            to_install.append(pkg)
    
    if not to_install:
        log_success("All required packages are already installed.")
        return True, installed_packages, []
    
    # Install missing packages
    log_info(f"Installing {len(to_install)} package(s): {', '.join(to_install)}")
    
    if dry_run:
        log_warning(f"[DRY RUN] Would install packages: {', '.join(to_install)}")
        return True, installed_packages, []
    
    # Use pacman to install the packages
    install_cmd = f"sudo pacman -S --needed --noconfirm {' '.join(to_install)}"
    log_info(f"Running: {install_cmd}")
    result = run_command(install_cmd, dry_run=False, debug=debug)
    
    if result is not None:
        newly_installed = []
        failed_packages = []
        
        # Verify installation
        for pkg in to_install:
            if check_package_installed(pkg, debug):
                newly_installed.append(pkg)
                log_success(f"Successfully installed package '{pkg}'")
            else:
                failed_packages.append(pkg)
                log_error(f"Failed to install package '{pkg}'")
        
        installed_packages.extend(newly_installed)
        
        if not failed_packages:
            log_success("All required packages were installed successfully.")
            return True, installed_packages, []
        else:
            log_error(f"Failed to install {len(failed_packages)} package(s): {', '.join(failed_packages)}")
            return False, installed_packages, failed_packages
    else:
        log_error("Package installation failed.")
        return False, installed_packages, to_install


def enable_libvirt_service(dry_run: bool = False, debug: bool = False) -> bool:
    """Enable and start the libvirt service.
    
    Args:
        dry_run: If True, don't actually enable or start the service
        debug: If True, print additional debug information
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not is_arch_based():
        log_error("This function is only supported on Arch-based systems.")
        return False
    
    # Check if systemctl is available
    if not shutil.which("systemctl"):
        log_error("systemctl not found. Cannot enable or start service.")
        return False
    
    # Enable libvirtd service
    enable_cmd = "sudo systemctl enable libvirtd.service"
    log_info("Enabling libvirtd service...")
    
    if dry_run:
        log_warning(f"[DRY RUN] Would run: {enable_cmd}")
    else:
        enable_result = run_command(enable_cmd, dry_run=False, debug=debug)
        if enable_result is None:
            log_error("Failed to enable libvirtd service.")
            return False
    
    # Start libvirtd service
    start_cmd = "sudo systemctl start libvirtd.service"
    log_info("Starting libvirtd service...")
    
    if dry_run:
        log_warning(f"[DRY RUN] Would run: {start_cmd}")
        return True
    else:
        start_result = run_command(start_cmd, dry_run=False, debug=debug)
        if start_result is None:
            log_error("Failed to start libvirtd service.")
            return False
    
    log_success("libvirtd service enabled and started successfully.")
    return True


def configure_user_permissions(user: str = None, dry_run: bool = False, debug: bool = False) -> bool:
    """Add the current user to the libvirt group.
    
    Args:
        user: Username to add to the libvirt group (if None, use current user)
        dry_run: If True, don't actually modify group
        debug: If True, print additional debug information
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not is_arch_based():
        log_error("This function is only supported on Arch-based systems.")
        return False
    
    # Determine username if not provided
    if user is None:
        user_cmd = "whoami"
        user_result = run_command(user_cmd, dry_run=False, debug=debug)
        if user_result is None:
            log_error("Failed to determine current username.")
            return False
        user = user_result.strip()
    
    # Add user to libvirt group
    group_cmd = f"sudo usermod -a -G libvirt {user}"
    log_info(f"Adding user '{user}' to the libvirt group...")
    
    if dry_run:
        log_warning(f"[DRY RUN] Would run: {group_cmd}")
        return True
    else:
        group_result = run_command(group_cmd, dry_run=False, debug=debug)
        if group_result is None:
            log_error(f"Failed to add user '{user}' to the libvirt group.")
            return False
    
    log_success(f"User '{user}' added to the libvirt group successfully.")
    log_warning("You may need to log out and log back in for the group changes to take effect.")
    return True


def setup_minimal_qemu_environment(user: str = None, dry_run: bool = False, debug: bool = False) -> Dict[str, Any]:
    """Set up a minimal QEMU environment with TPM, OVMF, and virt-manager support.
    
    Args:
        user: Username to add to the libvirt group (if None, use current user)
        dry_run: If True, don't actually modify the system
        debug: If True, print additional debug information
        
    Returns:
        Dict: Status information about the setup process
    """
    log_info("Setting up minimal QEMU environment...")
    
    result_info = {
        "status": False,
        "installed_packages": [],
        "failed_packages": [],
        "services_enabled": False,
        "user_configured": False
    }
    
    if not is_arch_based():
        log_error("This function is only supported on Arch-based systems.")
        return result_info
    
    # Install packages
    install_status, installed_pkgs, failed_pkgs = install_minimal_qemu_packages(dry_run, debug)
    result_info["installed_packages"] = installed_pkgs
    result_info["failed_packages"] = failed_pkgs
    
    if not install_status and not dry_run:
        log_error("Failed to install all required packages. QEMU setup incomplete.")
        return result_info
    
    # Enable and start libvirtd service
    service_status = enable_libvirt_service(dry_run, debug)
    result_info["services_enabled"] = service_status
    
    if not service_status and not dry_run:
        log_error("Failed to enable and start libvirtd service. QEMU setup incomplete.")
        # Continue anyway - packages are still installed
    
    # Configure user permissions
    user_status = configure_user_permissions(user, dry_run, debug)
    result_info["user_configured"] = user_status
    
    if not user_status and not dry_run:
        log_error("Failed to configure user permissions. QEMU setup incomplete.")
        # Continue anyway - services and packages are still configured
    
    # Print post-installation instructions
    log_info("------------------------------------------------------------")
    log_info("Post-installation instructions:")
    log_info("1. Restart your system or log out and back in to apply group changes")
    log_info("2. Launch virt-manager and create a new VM")
    log_info("3. To add GPU passthrough:")
    log_info("   - Click 'Add Hardware' > 'PCI Host Device' > Select your passthrough GPU")
    log_info("------------------------------------------------------------")
    
    # Set final status
    if dry_run:
        result_info["status"] = True  # Assume success in dry run
    else:
        result_info["status"] = (
            install_status and 
            (service_status or len(failed_pkgs) == 0) and 
            (user_status or len(failed_pkgs) == 0)
        )
    
    if result_info["status"]:
        log_success("QEMU environment set up successfully.")
    else:
        log_warning("QEMU environment setup completed with some issues. See above for details.")
    
    return result_info