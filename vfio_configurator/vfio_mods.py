"""VFIO driver module configuration handling."""

import shutil
import os
import re
from pathlib import Path
from typing import List, Optional, Dict, Tuple

from .utils import (
    log_info, log_success, log_warning, log_error, log_debug,
    create_timestamped_backup, run_command
)


def configure_vfio_modprobe(device_ids: List[str], dry_run: bool = False, debug: bool = False) -> bool:
    """
    Configure VFIO modules via /etc/modprobe.d/vfio.conf.
    
    Args:
        device_ids: List of device IDs to bind to vfio-pci
        dry_run: If True, don't actually modify files
        debug: If True, print additional debug information
        
    Returns:
        bool: True if configuration was successful or would be in dry_run mode
    """
    log_info("Configuring VFIO driver options via modprobe...")
    changes_made = False

    # Ensure target directory exists
    modprobe_dir = Path('/etc/modprobe.d')
    if not dry_run and not modprobe_dir.exists():
        try:
            log_info(f"Creating directory {modprobe_dir}...")
            modprobe_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log_error(f"Failed to create directory {modprobe_dir}: {e}")
            return False

    # 1. Configure vfio-pci options
    modprobe_conf_path = modprobe_dir / 'vfio.conf'
    ids_string = ','.join(device_ids)
    # disable_vga=1 prevents vfio-pci from binding to the primary device if it's VGA, needed if host uses same GPU initially
    # Added disable_idle_d3=1 based on common recommendations for stability with some devices
    options_line = f"options vfio-pci ids={ids_string} disable_vga=1 disable_idle_d3=1"
    # Enhanced softdep configuration based on Arch Linux recommendations
    softdep_lines = [
        "softdep drm pre: vfio-pci",  # General case for all display drivers
        "softdep amdgpu pre: vfio-pci",
        "softdep nouveau pre: vfio-pci",
        "softdep radeon pre: vfio-pci",
        "softdep nvidia pre: vfio-pci",  # For nvidia proprietary drivers
        "softdep i915 pre: vfio-pci"    # Intel graphics
    ]

    backup_path_modprobe: Optional[str] = None
    if dry_run:
        log_debug(f"[DRY RUN] Would write/update {modprobe_conf_path}:", debug)
        log_debug(f"  {options_line}", debug)
        for line in softdep_lines:
            log_debug(f"  {line}", debug)
    else:
        try:
            # Create backup
            backup_path_modprobe = create_timestamped_backup(str(modprobe_conf_path), dry_run=False, debug=debug)  # Force non-dry run for backup

            current_content = modprobe_conf_path.read_text() if modprobe_conf_path.exists() else ""
            new_content_lines = []

            # Process existing lines, removing old vfio-pci options/softdeps we manage
            existing_lines = current_content.splitlines()
            vfio_pci_option_found = False
            existing_softdeps = set()

            for line in existing_lines:
                stripped_line = line.strip()
                if not stripped_line or stripped_line.startswith("#"):
                    new_content_lines.append(line)  # Keep comments and blank lines
                    continue

                if stripped_line.startswith("options vfio-pci"):
                    # Replace the first occurrence, comment out others
                    if not vfio_pci_option_found:
                        new_content_lines.append(options_line)
                        vfio_pci_option_found = True
                        log_debug(f"Replacing existing options vfio-pci line.", debug)
                    else:
                        new_content_lines.append(f"# {line} # Commented out duplicate by script")
                        log_debug(f"Commenting out duplicate options vfio-pci line.", debug)
                    continue  # Move to next line

                elif stripped_line.startswith("softdep ") and " pre: vfio-pci" in stripped_line:
                    # Track existing softdeps we manage
                    existing_softdeps.add(stripped_line)
                    log_debug(f"Found existing softdep line: {line}", debug)
                    # Keep it for now, we'll add ours later if missing
                    new_content_lines.append(line)

                else:  # Keep other unrelated lines
                    new_content_lines.append(line)

            # If no options line was found/replaced, add it
            if not vfio_pci_option_found:
                new_content_lines.append(options_line)
                log_debug(f"Adding new options vfio-pci line.", debug)

            # Add our required softdep lines if they don't already exist
            for softdep_line in softdep_lines:
                if softdep_line not in existing_softdeps:
                    new_content_lines.append(softdep_line)
                    log_debug(f"Adding missing softdep line: {softdep_line}", debug)

            # Write the new content
            new_content_str = "\n".join(new_content_lines) + "\n"
            if new_content_str != current_content:
                modprobe_conf_path.write_text(new_content_str)
                log_success(f"Updated VFIO configuration in {modprobe_conf_path}")
                changes_made = True
            else:
                log_info(f"VFIO configuration in {modprobe_conf_path} is already up-to-date.")

        except Exception as e:
            log_error(f"Failed to write VFIO config to {modprobe_conf_path}: {e}")
            # Attempt to restore backup if created
            if backup_path_modprobe and Path(backup_path_modprobe).exists():
                try:
                    shutil.move(backup_path_modprobe, str(modprobe_conf_path))
                    log_info(f"Restored backup file {backup_path_modprobe} to {modprobe_conf_path}")
                except Exception as restore_e:
                    log_error(f"Failed to restore backup {backup_path_modprobe}: {restore_e}")
            return False

    # 2. Ensure modules load early via /etc/modules-load.d/
    # Note: As of kernel 6.2, vfio_virqfd functionality has been folded into base vfio module
    # but we keep it for backward compatibility with older kernels
    modules_load_dir = Path('/etc/modules-load.d')
    if not dry_run and not modules_load_dir.exists():
        try:
            log_info(f"Creating directory {modules_load_dir}...")
            modules_load_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log_error(f"Failed to create directory {modules_load_dir}: {e}")
            # Non-fatal, vfio-pci options might still load them implicitly
            log_warning("Proceeding without creating /etc/modules-load.d/ configuration.")

    modules_load_path = modules_load_dir / 'vfio-pci-load.conf'  # Slightly different name
    vfio_modules_to_load = [
        "vfio",
        "vfio_iommu_type1",
        "vfio_pci"
    ]
    
    # Add vfio_virqfd only for kernels < 6.2 for backward compatibility
    kernel_version = get_kernel_version()
    if kernel_version and (kernel_version[0] < 6 or (kernel_version[0] == 6 and kernel_version[1] < 2)):
        vfio_modules_to_load.append("vfio_virqfd")
        log_debug(f"Adding vfio_virqfd module for kernel {kernel_version}", debug)
    else:
        log_debug(f"Skipping vfio_virqfd as kernel {kernel_version} has this integrated into vfio module", debug)
        
    modules_load_content = "\n".join(vfio_modules_to_load) + "\n"
    backup_path_load: Optional[str] = None

    if dry_run:
        log_debug(f"[DRY RUN] Would write to {modules_load_path}:", debug)
        log_debug(f"Content:\n{modules_load_content}", debug)
    else:
        try:
            # Backup existing if it exists
            backup_path_load = create_timestamped_backup(str(modules_load_path), dry_run=False, debug=debug)
            existing_content = modules_load_path.read_text() if modules_load_path.exists() else ""

            if existing_content != modules_load_content:
                modules_load_path.write_text(modules_load_content)
                log_success(f"Ensured VFIO modules are configured to load via {modules_load_path}")
                changes_made = True
            else:
                log_info(f"VFIO module load configuration {modules_load_path} is already up-to-date.")

        except Exception as e:
            log_error(f"Failed to write VFIO module load config to {modules_load_path}: {e}")
            if backup_path_load and Path(backup_path_load).exists():
                try:
                    shutil.move(backup_path_load, str(modules_load_path))
                    log_info(f"Restored backup file {backup_path_load} to {modules_load_path}")
                except Exception as restore_e:
                    log_error(f"Failed to restore backup {backup_path_load}: {restore_e}")
            return False
    
    # 3. Configure initramfs
    # Instead of directly calling configure_vfio_initramfs, we now just prepare configs
    # and leave the actual initramfs update to be handled by the main script via initramfs.py
    from . import initramfs
    
    systems = initramfs.detect_initramfs_systems(debug)
    if systems:
        log_info(f"Detected initramfs systems: {', '.join(systems)}")
        
        if 'mkinitcpio' in systems:
            initramfs.ensure_mkinitcpio_modules(vfio_modules_to_load, debug)
            
        if 'dracut' in systems:
            initramfs.ensure_dracut_modules(vfio_modules_to_load, debug)
            
        if 'booster' in systems:
            initramfs.ensure_booster_modules(vfio_modules_to_load, debug)
    else:
        log_warning("No supported initramfs systems detected (mkinitcpio, booster, dracut).")
        log_warning("You will need to manually update your initramfs to include VFIO modules.")
    
    if dry_run:
        log_success("[DRY RUN] VFIO modprobe configuration would be updated")
        return True
    
    return True  # Overall success


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