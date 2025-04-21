"""Handles updating the initial RAM disk image to include VFIO modules."""

import os
import re
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any, Set, Tuple

from .utils import (
    log_info, log_success, log_warning, log_error, log_debug,
    run_command, get_distro_info, backup_file, create_timestamped_backup
)


def update_initramfs(dry_run: bool = False, debug: bool = False) -> bool:
    """
    Updates the initramfs to include VFIO modules.
    
    Different distributions have different tools for updating the initramfs.
    This function detects the distribution and uses the appropriate method.
    
    Args:
        dry_run: If True, simulate operations without making changes.
        debug: If True, print debug messages.
    
    Returns:
        True if successful, False otherwise.
    """
    log_info("Updating initramfs to include VFIO modules...")
    
    # First detect which initramfs systems are present
    systems = detect_initramfs_systems(debug)
    
    if not systems:
        log_warning("No supported initramfs systems detected.")
        return False
    
    log_info(f"Detected initramfs systems: {', '.join(systems)}")
    
    vfio_modules = ['vfio', 'vfio_iommu_type1', 'vfio_pci']
    
    # Check kernel version - add vfio_virqfd only for older kernels
    kernel_version = get_kernel_version()
    if kernel_version and (kernel_version[0] < 6 or (kernel_version[0] == 6 and kernel_version[1] < 2)):
        vfio_modules.append('vfio_virqfd')
        log_debug(f"Including vfio_virqfd for kernel {kernel_version}", debug)
    else:
        log_debug(f"Skipping vfio_virqfd as kernel {kernel_version} has this integrated into vfio module", debug)
    
    # Check if we're on an Arch-based system
    distro_info = get_distro_info()
    distro_name = distro_info.get('id', '').lower() if distro_info else ''
    is_arch_based = distro_name in ['arch', 'manjaro', 'endeavouros', 'garuda'] or os.path.exists("/etc/arch-release")
    
    # Try to determine the default initramfs system for this distribution
    default_system = detect_default_initramfs_system(distro_name, systems, debug)
    if default_system:
        log_info(f"Detected default initramfs system for this distribution: {default_system}")
    
    # Try updating each system that was found, prioritizing the default system
    success = False
    
    # Try the default system first if we detected one
    if default_system and default_system in systems:
        log_info(f"Trying default initramfs system: {default_system}")
        if default_system == 'mkinitcpio':
            if ensure_mkinitcpio_modules(vfio_modules, debug):
                if update_mkinitcpio(dry_run, debug):
                    success = True
                    return success
        elif default_system == 'dracut':
            if ensure_dracut_modules(vfio_modules, debug):
                if update_dracut_custom(dry_run, debug, is_arch_based):
                    success = True
                    return success
        elif default_system == 'booster':
            if ensure_booster_modules(vfio_modules, debug):
                if update_booster(dry_run, debug):
                    success = True
                    return success
        elif default_system == 'debian':
            if ensure_initramfs_modules_debian(vfio_modules, debug):
                if update_initramfs_debian_based(dry_run, debug):
                    success = True
                    return success
    
    # If default system not found or failed, try distribution-specific approach
    if not success:
        if is_arch_based:
            # For Arch-based systems
            if 'mkinitcpio' in systems:
                if ensure_mkinitcpio_modules(vfio_modules, debug):
                    if update_mkinitcpio(dry_run, debug):
                        success = True
                        return success
            if 'dracut' in systems:
                if ensure_dracut_modules(vfio_modules, debug):
                    if update_dracut_custom(dry_run, debug, is_arch_based):
                        success = True
                        return success
        elif distro_name in ['ubuntu', 'debian', 'pop', 'linuxmint', 'elementary'] and 'debian' in systems:
            if ensure_initramfs_modules_debian(vfio_modules, debug):
                if update_initramfs_debian_based(dry_run, debug):
                    success = True
                    return success
        elif distro_name in ['fedora', 'rhel', 'centos', 'rocky', 'alma'] and 'dracut' in systems:
            if ensure_dracut_modules(vfio_modules, debug):
                if update_initramfs_fedora_based(dry_run, debug):
                    success = True
                    return success
    
    # Standard priority order for other systems or if distribution-specific approach failed
    if 'mkinitcpio' in systems and not success:
        if ensure_mkinitcpio_modules(vfio_modules, debug):
            if update_mkinitcpio(dry_run, debug):
                success = True
    
    if 'dracut' in systems and not success:
        if ensure_dracut_modules(vfio_modules, debug):
            if update_dracut_custom(dry_run, debug, is_arch_based):
                success = True
    
    if 'booster' in systems and not success:
        if ensure_booster_modules(vfio_modules, debug):
            if update_booster(dry_run, debug):
                success = True
                
    if 'debian' in systems and not success:
        if ensure_initramfs_modules_debian(vfio_modules, debug):
            if update_initramfs_debian_based(dry_run, debug):
                success = True
    
    # If still no success, try generic approach
    if not success:
        log_warning("Distribution-specific approach failed or unsupported distribution.")
        log_warning("Attempting generic initramfs update approach...")
        success = update_initramfs_generic(dry_run, debug)
    
    return success


def detect_initramfs_systems(debug: bool = False) -> Set[str]:
    """
    Detect which initramfs systems are present on the system.
    
    Returns:
        Set of strings representing detected initramfs systems
    """
    systems = set()
    
    # Check for mkinitcpio
    if Path('/etc/mkinitcpio.conf').exists() or shutil.which('mkinitcpio'):
        systems.add('mkinitcpio')
        log_debug("Detected mkinitcpio initramfs system", debug)
    
    # Check for dracut
    if (Path('/etc/dracut.conf').exists() or 
        Path('/etc/dracut.conf.d').exists() or 
        shutil.which('dracut')):
        systems.add('dracut')
        log_debug("Detected dracut initramfs system", debug)
    
    # Check for booster
    if Path('/etc/booster.yaml').exists() or Path('/etc/booster.d').exists() or shutil.which('booster'):
        systems.add('booster')
        log_debug("Detected booster initramfs system", debug)
        
    # Check for Debian/Ubuntu/Pop!_OS (update-initramfs)
    if Path('/etc/initramfs-tools').exists() or shutil.which('update-initramfs'):
        systems.add('debian')
        log_debug("Detected Debian/Ubuntu/Pop!_OS initramfs system (update-initramfs)", debug)
    
    return systems


def detect_default_initramfs_system(distro_name: str, detected_systems: Set[str], debug: bool = False) -> Optional[str]:
    """
    Detect the default initramfs system for a given distribution.
    
    Args:
        distro_name: The distribution name, lowercase
        detected_systems: Set of detected initramfs systems
        debug: Enable debug output
        
    Returns:
        String with default system name or None if unknown
    """
    # Check for systemd-boot or dracut symlinks in /usr/lib/kernel
    is_dracut_default = (
        os.path.exists("/usr/lib/dracut/dracut.conf.d") or
        os.path.exists("/usr/lib/kernel/install.d/50-dracut.install")
    )
    
    is_mkinitcpio_default = (
        os.path.exists("/usr/lib/kernel/install.d/50-mkinitcpio.install") or
        os.path.exists("/usr/share/libalpm/hooks/60-mkinitcpio-remove.hook")
    )
    
    is_booster_default = (
        os.path.exists("/usr/lib/kernel/install.d/50-booster.install") or
        os.path.exists("/usr/lib/booster")
    )
    
    # Specific distribution checks
    if distro_name in ['arch', 'manjaro']:
        return 'mkinitcpio' if 'mkinitcpio' in detected_systems else None
    elif distro_name in ['garuda', 'endeavouros']:
        if 'dracut' in detected_systems:
            return 'dracut'
        elif 'mkinitcpio' in detected_systems:
            return 'mkinitcpio'
    elif distro_name in ['fedora', 'centos', 'rhel', 'rocky', 'alma']:
        return 'dracut' if 'dracut' in detected_systems else None
    elif distro_name in ['ubuntu', 'debian', 'pop', 'linuxmint', 'elementary']:
        return 'debian' if 'debian' in detected_systems else None
    elif distro_name in ['opensuse', 'suse']:
        return 'dracut' if 'dracut' in detected_systems else None
    
    # If no specific distro match, use file-based detection
    if is_dracut_default and 'dracut' in detected_systems:
        return 'dracut'
    elif is_mkinitcpio_default and 'mkinitcpio' in detected_systems:
        return 'mkinitcpio'
    elif is_booster_default and 'booster' in detected_systems:
        return 'booster'
    
    # As a last resort, if only one system is detected, use that
    if len(detected_systems) == 1:
        return list(detected_systems)[0]
    
    return None


def update_mkinitcpio(dry_run: bool = False, debug: bool = False) -> bool:
    """
    Update initramfs using mkinitcpio.
    
    Returns:
        True if successful, False otherwise.
    """
    cmd = "mkinitcpio -P"
    log_info(f"Running: {cmd}")
    if dry_run:
        log_info("Dry run enabled, not executing command.")
        return True
    output = run_command(cmd, debug=debug)
    
    if output is not None:
        log_success("Successfully updated initramfs with mkinitcpio.")
        return True
    else:
        log_error("Failed to update initramfs with mkinitcpio.")
        return False


def update_dracut_custom(dry_run: bool = False, debug: bool = False, is_arch_based: bool = False) -> bool:
    """
    Update initramfs using dracut with custom handling for different systems.
    
    Args:
        dry_run: If True, simulate operations without making changes.
        debug: If True, print debug messages.
        is_arch_based: If True, use Arch-specific dracut commands.
        
    Returns:
        True if successful, False otherwise.
    """
    if is_arch_based:
        # For Arch-based systems, we need to specify the output path
        try:
            # Try to determine the kernel version
            kernel_ver = run_command("uname -r", debug=debug)
            if kernel_ver:
                kernel_ver = kernel_ver.strip()
                
                # Create the target path for initramfs
                initramfs_dir = "/boot"
                os.makedirs(initramfs_dir, exist_ok=True)
                
                # On some systems like Garuda we need to use a specific output path
                cmd = f"dracut -f /boot/initramfs-{kernel_ver}.img {kernel_ver}"
                log_info(f"Running: {cmd}")
                if dry_run:
                    log_info("Dry run enabled, not executing command.")
                    return True
                output = run_command(cmd, debug=debug)
                
                if output is not None:
                    log_success("Successfully updated initramfs with dracut.")
                    return True
                else:
                    log_error("Failed to update initramfs with dracut.")
                    return False
            else:
                log_error("Failed to determine kernel version for dracut.")
                return False
        except Exception as e:
            log_error(f"Error during dracut invocation: {e}")
            return False
    else:
        # Standard dracut command for non-Arch systems
        cmd = "dracut --force"
        log_info(f"Running: {cmd}")
        if dry_run:
            log_info("Dry run enabled, not executing command.")
            return True
        output = run_command(cmd, debug=debug)
        
        if output is not None:
            log_success("Successfully updated initramfs with dracut.")
            return True
        else:
            log_error("Failed to update initramfs with dracut.")
            return False


def update_booster(dry_run: bool = False, debug: bool = False) -> bool:
    """
    Update initramfs using booster.
    
    Returns:
        True if successful, False otherwise.
    """
    cmd = "booster build"
    log_info(f"Running: {cmd}")
    if dry_run:
        log_info("Dry run enabled, not executing command.")
        return True
    output = run_command(cmd, debug=debug)
    
    if output is not None:
        log_success("Successfully updated initramfs with booster.")
        return True
    else:
        log_error("Failed to update initramfs with booster.")
        return False


def ensure_booster_modules(modules: List[str], debug: bool = False) -> bool:
    """
    Ensure that VFIO modules are configured to load early with booster.
    
    Args:
        modules: List of modules to include
        debug: Enable debug output
        
    Returns:
        True if successful, False otherwise
    """
    log_info("Configuring booster for early VFIO module loading...")
    booster_path = Path('/etc/booster.yaml')
    booster_dir = Path('/etc/booster.d')
    
    # Create directory if needed
    if not booster_dir.exists():
        try:
            booster_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log_error(f"Failed to create directory {booster_dir}: {e}")
            return False
    
    # Use booster.d directory for our configuration
    vfio_booster_path = booster_dir / 'vfio.yaml'
    
    # Comma-separated list of modules
    modules_str = ",".join(modules)
    config_content = f"modules_force_load: {modules_str}\n"
    
    try:
        backup_path = create_timestamped_backup(str(vfio_booster_path), False, debug)
        
        # Write the configuration
        vfio_booster_path.write_text(config_content)
        log_success(f"Created/updated booster configuration at {vfio_booster_path}")
        return True
        
    except Exception as e:
        log_error(f"Failed to configure booster: {e}")
        return False


def update_initramfs_debian_based(dry_run: bool = False, debug: bool = False) -> bool:
    """
    Updates the initramfs on Debian-based systems using update-initramfs.
    
    Returns:
        True if successful, False otherwise.
    """
    # Check if update-initramfs exists
    update_bin = shutil.which('update-initramfs')
    if not update_bin:
        log_error("update-initramfs not found. Is initramfs-tools installed?")
        return False
    
    # Ensure vfio modules will be loaded
    # Get kernel version to check if vfio_virqfd is needed
    kernel_version = get_kernel_version()
    modules_to_add = ['vfio', 'vfio_iommu_type1', 'vfio_pci']
    if kernel_version and (kernel_version[0] < 6 or (kernel_version[0] == 6 and kernel_version[1] < 2)):
        modules_to_add.append('vfio_virqfd')
        
    ensure_initramfs_modules_debian(modules_to_add, debug)
    
    # Update all initramfs images
    cmd = "update-initramfs -u -k all"
    log_info(f"Running: {cmd}")
    if dry_run:
        log_info("Dry run enabled, not executing command.")
        return True
    output = run_command(cmd, debug=debug)
    
    if output is not None:
        log_success("Successfully updated initramfs.")
        return True
    else:
        log_error("Failed to update initramfs.")
        return False


def ensure_initramfs_modules_debian(modules: List[str], debug: bool = False) -> bool:
    """
    Ensures the specified modules are included in the Debian initramfs.
    
    Args:
        modules: List of module names to include.
        debug: Enable debug output.
        
    Returns:
        True if successful, False otherwise.
    """
    # Path to the modules file
    modules_file = "/etc/initramfs-tools/modules"
    
    # Check if the file exists
    if not os.path.isfile(modules_file):
        log_error(f"Modules file not found: {modules_file}")
        log_error("Is initramfs-tools installed correctly?")
        return False
        
    # Backup the file
    if not backup_file(modules_file):
        log_warning(f"Could not back up {modules_file}. Proceeding anyway.")
    
    # Read the current content
    try:
        with open(modules_file, 'r') as f:
            content = f.read()
    except Exception as e:
        log_error(f"Failed to read {modules_file}: {e}")
        return False
        
    # Check if each module is already in the file
    lines = content.splitlines()
    modules_to_add = []
    
    for module in modules:
        # Check if the module is already in the file (ignoring comments)
        if not any(re.search(rf"^\s*{module}\s*($|\s+)", line) for line in lines):
            modules_to_add.append(module)
    
    # If there are modules to add, update the file
    if modules_to_add:
        try:
            with open(modules_file, 'a') as f:
                f.write("\n# Added by VFIO Configurator\n")
                for module in modules_to_add:
                    f.write(f"{module}\n")
                    log_info(f"Added module to initramfs: {module}")
            log_success(f"Updated {modules_file} with required modules.")
        except Exception as e:
            log_error(f"Failed to update {modules_file}: {e}")
            return False
    else:
        log_info("All required modules already in initramfs.")
        
    return True


def update_initramfs_fedora_based(dry_run: bool = False, debug: bool = False) -> bool:
    """
    Updates the initramfs on Fedora-based systems using dracut.
    
    Returns:
        True if successful, False otherwise.
    """
    # Check if dracut exists
    dracut_bin = shutil.which('dracut')
    if not dracut_bin:
        log_error("dracut not found. Is it installed?")
        return False
    
    # Ensure the appropriate config exists in /etc/dracut.conf.d/
    # Get kernel version to check if vfio_virqfd is needed
    kernel_version = get_kernel_version()
    modules_to_add = ['vfio', 'vfio_iommu_type1', 'vfio_pci']
    if kernel_version and (kernel_version[0] < 6 or (kernel_version[0] == 6 and kernel_version[1] < 2)):
        modules_to_add.append('vfio_virqfd')
        
    ensure_dracut_modules(modules_to_add, debug)
    
    # Regenerate all initramfs images 
    cmd = "dracut -f"
    log_info(f"Running: {cmd}")
    if dry_run:
        log_info("Dry run enabled, not executing command.")
        return True
    output = run_command(cmd, debug=debug)
    
    if output is not None:
        log_success("Successfully updated initramfs.")
        return True
    else:
        log_error("Failed to update initramfs.")
        return False


def ensure_dracut_modules(modules: List[str], debug: bool = False) -> bool:
    """
    Ensures the specified modules are included in the dracut configuration.
    
    Args:
        modules: List of module names to include.
        debug: Enable debug output.
        
    Returns:
        True if successful, False otherwise.
    """
    # Path to dracut VFIO config
    config_dir = "/etc/dracut.conf.d"
    config_file = os.path.join(config_dir, "vfio.conf")
    
    # Create the config directory if it doesn't exist
    if not os.path.isdir(config_dir):
        try:
            os.makedirs(config_dir, exist_ok=True)
            log_info(f"Created directory: {config_dir}")
        except Exception as e:
            log_error(f"Failed to create directory {config_dir}: {e}")
            return False
    
    # Space-separated list of modules with quotes for force_drivers
    modules_str = " ".join(modules)
    config_content = f'force_drivers+=" {modules_str} "\n'
    
    try:
        backup_path = create_timestamped_backup(config_file, False, debug)
        
        # Write the configuration
        with open(config_file, 'w') as f:
            f.write("# Generated by VFIO Configurator\n")
            f.write(config_content)
        log_success(f"Created/updated dracut configuration at {config_file}")
        return True
        
    except Exception as e:
        log_error(f"Failed to configure dracut: {e}")
        return False


def update_initramfs_arch_based(dry_run: bool = False, debug: bool = False) -> bool:
    """
    Updates the initramfs on Arch-based systems using mkinitcpio.
    
    Returns:
        True if successful, False otherwise.
    """
    # First check for mkinitcpio - the preferred tool for Arch-based systems
    mkinitcpio_bin = shutil.which('mkinitcpio')
    if not mkinitcpio_bin:
        log_error("mkinitcpio not found. You may need to manually install it.")
        return False
    
    # Get list of modules to add
    kernel_version = get_kernel_version()
    modules_to_add = ['vfio', 'vfio_iommu_type1', 'vfio_pci']
    if kernel_version and (kernel_version[0] < 6 or (kernel_version[0] == 6 and kernel_version[1] < 2)):
        modules_to_add.append('vfio_virqfd')
    
    success = False
    
    # Try mkinitcpio if available
    if mkinitcpio_bin:
        # Ensure modules are in mkinitcpio.conf
        if ensure_mkinitcpio_modules(modules_to_add, debug):
            # First try the standard command
            cmd = "mkinitcpio -P"
            log_info(f"Running: {cmd}")
            if dry_run:
                log_info("Dry run enabled, not executing command.")
                return True
            
            output = run_command(cmd, debug=debug)
            if output is not None:
                log_success("Successfully updated initramfs with mkinitcpio.")
                return True
            else:
                # If standard approach fails, try a workaround for Garuda/other Arch derivatives
                log_warning("Standard mkinitcpio command failed, trying alternative approach...")
                
                # Get list of installed kernels
                kernel_cmd = "ls /usr/lib/modules/"
                kernel_list = run_command(kernel_cmd, debug=debug)
                if kernel_list:
                    kernels = kernel_list.strip().split('\n')
                    for kernel in kernels:
                        if os.path.isdir(f"/usr/lib/modules/{kernel}"):
                            # Try to build initramfs for each kernel specifically
                            cmd = f"mkinitcpio -p {kernel}"
                            log_info(f"Building initramfs for kernel: {kernel}")
                            output = run_command(cmd, debug=debug)
                            if output is not None:
                                log_success(f"Successfully built initramfs for kernel: {kernel}")
                                success = True
                    
                    if success:
                        log_success("Successfully updated initramfs for all available kernels.")
                        return True
                    else:
                        log_error("Failed to update initramfs for any kernel.")
                        return False
                else:
                    log_error("Failed to list available kernels.")
                    return False
    
    # If mkinitcpio failed or isn't available, check for dracut as a fallback on Arch
    dracut_bin = shutil.which('dracut')
    if dracut_bin and not success:
        log_info("Attempting to use dracut as fallback on Arch-based system")
        # Configure dracut to include VFIO modules
        if ensure_dracut_modules(modules_to_add, debug):
            # Try to use dracut in a more Arch-friendly way
            try:
                # Try to determine the kernel version
                kernel_ver = run_command("uname -r", debug=debug)
                if kernel_ver:
                    kernel_ver = kernel_ver.strip()
                    
                    # Create the target path for initramfs
                    initramfs_dir = "/boot"
                    os.makedirs(initramfs_dir, exist_ok=True)
                    
                    # On some systems like Garuda we need to use a specific output path
                    cmd = f"dracut -f /boot/initramfs-{kernel_ver}.img {kernel_ver}"
                    log_info(f"Running: {cmd}")
                    if dry_run:
                        log_info("Dry run enabled, not executing command.")
                        return True
                    output = run_command(cmd, debug=debug)
                    
                    if output is not None:
                        log_success("Successfully updated initramfs with dracut.")
                        return True
                    else:
                        log_error("Failed to update initramfs with dracut.")
                        return False
                else:
                    log_error("Failed to determine kernel version for dracut.")
                    return False
            except Exception as e:
                log_error(f"Error during dracut fallback: {e}")
                return False
    
    # All methods failed
    log_error("Failed to update initramfs on Arch-based system. Neither mkinitcpio nor dracut worked.")
    log_error("You may need to manually update your initramfs to include VFIO modules.")
    log_error("For reference, you should ensure these modules are included: " + ", ".join(modules_to_add))
    return False


def ensure_mkinitcpio_modules(modules: List[str], debug: bool = False) -> bool:
    """
    Ensures the specified modules are included in the mkinitcpio.conf.
    
    Args:
        modules: List of module names to include.
        debug: Enable debug output.
        
    Returns:
        True if successful, False otherwise.
    """
    # Path to mkinitcpio.conf
    config_file = "/etc/mkinitcpio.conf"
    
    # Check if the file exists
    if not os.path.isfile(config_file):
        log_error(f"Configuration file not found: {config_file}")
        return False
        
    # Backup the file
    if not backup_file(config_file):
        log_warning(f"Could not back up {config_file}. Proceeding anyway.")
    
    # Read the current content
    try:
        with open(config_file, 'r') as f:
            content = f.read()
    except Exception as e:
        log_error(f"Failed to read {config_file}: {e}")
        return False
        
    # Check and update MODULES array in mkinitcpio.conf
    modules_regex = r'^MODULES\s*=\s*\((.*?)\)'
    match = re.search(modules_regex, content, re.MULTILINE)
    
    # Also ensure modconf hook is present 
    hooks_regex = r'^HOOKS\s*=\s*\((.*?)\)'
    hooks_match = re.search(hooks_regex, content, re.MULTILINE)
    
    modules_str = " ".join(modules)
    new_content = content
    changes_needed = False
    
    # Handle MODULES line
    if match:
        # Extract existing modules
        existing_modules = match.group(1).strip()
        # Check which VFIO modules are already present
        existing_modules_list = [m.strip() for m in existing_modules.split()]
        vfio_modules_needed = [m for m in modules if m not in existing_modules_list]
        
        if vfio_modules_needed:
            # Add the missing VFIO modules at the beginning to ensure they load first
            if existing_modules:
                new_modules_line = f"MODULES=({modules_str} {existing_modules})"
            else:
                new_modules_line = f"MODULES=({modules_str})"
            new_content = re.sub(modules_regex, new_modules_line, new_content, flags=re.MULTILINE)
            changes_needed = True
            log_success(f"Adding VFIO modules to mkinitcpio.conf: {', '.join(vfio_modules_needed)}")
    else:
        # No MODULES line found, add one
        new_content = f"MODULES=({modules_str})\n" + new_content
        changes_needed = True
        log_success(f"Adding MODULES line with VFIO modules to mkinitcpio.conf")
    
    # Ensure modconf hook is present
    if hooks_match:
        existing_hooks = hooks_match.group(1).strip()
        existing_hooks_list = [h.strip() for h in existing_hooks.split()]
        
        if 'modconf' not in existing_hooks_list:
            # Add modconf hook if missing (after base hook if present)
            if 'base' in existing_hooks_list:
                base_index = existing_hooks_list.index('base')
                existing_hooks_list.insert(base_index + 1, 'modconf')
            else:
                # If no base, add modconf at the beginning
                existing_hooks_list.insert(0, 'modconf')
            
            new_hooks_line = f"HOOKS=({' '.join(existing_hooks_list)})"
            new_content = re.sub(hooks_regex, new_hooks_line, new_content, flags=re.MULTILINE)
            changes_needed = True
            log_success("Adding modconf hook to mkinitcpio.conf")
    
    # Write the updated content if changes were made
    if changes_needed:
        try:
            with open(config_file, 'w') as f:
                f.write(new_content)
            log_success(f"Updated {config_file} with required modules and hooks")
            return True
        except Exception as e:
            log_error(f"Failed to update {config_file}: {e}")
            return False
    else:
        log_info("mkinitcpio.conf is already configured with all required modules and hooks.")
        return True


def update_initramfs_suse_based(dry_run: bool = False, debug: bool = False) -> bool:
    """
    Updates the initramfs on SUSE-based systems using mkinitrd.
    
    Returns:
        True if successful, False otherwise.
    """
    # Check if mkinitrd exists
    mkinitrd_bin = shutil.which('mkinitrd')
    if not mkinitrd_bin:
        log_error("mkinitrd not found. Is it installed?")
        return False
    
    # Get kernel version to check if vfio_virqfd is needed
    kernel_version = get_kernel_version()
    modules_to_add = ['vfio', 'vfio_iommu_type1', 'vfio_pci']
    if kernel_version and (kernel_version[0] < 6 or (kernel_version[0] == 6 and kernel_version[1] < 2)):
        modules_to_add.append('vfio_virqfd')
    
    # Ensure the appropriate modules are in the config
    if not ensure_suse_modules(modules_to_add, debug):
        return False
    
    # Regenerate the initramfs 
    cmd = "mkinitrd"
    log_info(f"Running: {cmd}")
    if dry_run:
        log_info("Dry run enabled, not executing command.")
        return True
    output = run_command(cmd, debug=debug)
    
    if output is not None:
        log_success("Successfully updated initramfs.")
        return True
    else:
        log_error("Failed to update initramfs.")
        return False


def ensure_suse_modules(modules: List[str], debug: bool = False) -> bool:
    """
    Ensures the specified modules are included in the SUSE initrd configuration.
    
    Args:
        modules: List of module names to include.
        debug: Enable debug output.
        
    Returns:
        True if successful, False otherwise.
    """
    # Path to SUSE config (could be in /etc/dracut.conf.d/ for newer versions)
    config_file = "/etc/sysconfig/kernel"
    dracut_dir = "/etc/dracut.conf.d"
    dracut_file = os.path.join(dracut_dir, "vfio.conf")
    
    # Try the SUSE specific method first
    if os.path.isfile(config_file):
        # Backup the file
        if not backup_file(config_file):
            log_warning(f"Could not back up {config_file}. Proceeding anyway.")
        
        # Read the current content
        try:
            with open(config_file, 'r') as f:
                content = f.read()
        except Exception as e:
            log_error(f"Failed to read {config_file}: {e}")
            return False
            
        # Check if INITRD_MODULES line exists
        initrd_regex = r'^INITRD_MODULES="([^"]*)"'
        match = re.search(initrd_regex, content, re.MULTILINE)
        
        if match:
            current_modules = [m.strip() for m in match.group(1).split() if m.strip()]
            missing_modules = [m for m in modules if m not in current_modules]
            
            if not missing_modules:
                log_info("All required modules already in SUSE kernel configuration.")
                return True
                
            # Update the INITRD_MODULES line
            new_modules_line = f'INITRD_MODULES="{" ".join(current_modules + missing_modules)}"'
            updated_content = re.sub(initrd_regex, new_modules_line, content, flags=re.MULTILINE)
            
            # Write the updated content
            try:
                with open(config_file, 'w') as f:
                    f.write(updated_content)
                log_success(f"Updated {config_file} with required modules.")
                return True
            except Exception as e:
                log_error(f"Failed to update {config_file}: {e}")
                return False
        else:
            # If INITRD_MODULES line doesn't exist, append it
            try:
                with open(config_file, 'a') as f:
                    f.write("\n# Added by VFIO Configurator\n")
                    f.write(f'INITRD_MODULES="{" ".join(modules)}"\n')
                log_success(f"Added INITRD_MODULES to {config_file}.")
                return True
            except Exception as e:
                log_error(f"Failed to update {config_file}: {e}")
                return False
    # Try using dracut method for newer SUSE versions
    elif os.path.isdir(dracut_dir):
        return ensure_dracut_modules(modules, debug)
    else:
        log_error("Could not find an appropriate method to update initramfs modules.")
        log_error("You may need to manually add vfio, vfio_iommu_type1, vfio_pci to your initramfs.")
        return False


def update_initramfs_generic(dry_run: bool = False, debug: bool = False) -> bool:
    """
    Generic method to update initramfs when distribution-specific method is not available.
    
    Returns:
        True if one method succeeds, False otherwise.
    """
    log_warning("Using fallback methods to update initramfs...")
    
    # Try various common methods in order
    methods = [
        ('update-initramfs', update_initramfs_debian_based),
        ('dracut', update_initramfs_fedora_based),
        ('mkinitcpio', update_initramfs_arch_based),
        ('mkinitrd', update_initramfs_suse_based)
    ]
    
    for command, method in methods:
        if shutil.which(command):
            log_info(f"Found {command}, attempting to use it...")
            result = method(dry_run, debug)
            if result:
                return True
    
    log_error("Could not find a suitable method to update initramfs.")
    log_error("You may need to manually update your initramfs to include vfio modules.")
    return False


def get_kernel_version() -> Optional[Tuple[int, int, int]]:
    """
    Get the current kernel version as a tuple (major, minor, patch).
    This function is distribution-agnostic and handles various kernel version formats.
    
    Returns:
        Optional[Tuple[int, int, int]]: A tuple of (major, minor, patch) version numbers,
                                         or None if version couldn't be determined
    """
    try:
        # First attempt: Use uname -r directly
        output = run_command("uname -r")
        
        if not output:
            # Second attempt: Try reading from /proc/version
            try:
                with open('/proc/version', 'r') as f:
                    output = f.read().strip()
            except Exception:
                output = None
        
        if not output:
            # Third attempt: Try using python's platform module
            try:
                import platform
                output = platform.release()
            except Exception:
                log_error("Failed to determine kernel version using multiple methods")
                return None
        
        # Extract version numbers from string like "6.1.0-rc3-1-custom" or longer strings
        # This regex looks for the first occurrence of major.minor(.patch) in the string
        match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', output)
        if match:
            major = int(match.group(1))
            minor = int(match.group(2))
            patch = int(match.group(3)) if match.group(3) else 0
            log_debug(f"Detected kernel version: {major}.{minor}.{patch}")
            return (major, minor, patch)
        else:
            log_error(f"Could not parse kernel version from: {output}")
            return None
    except Exception as e:
        log_error(f"Failed to determine kernel version: {e}")
        return None