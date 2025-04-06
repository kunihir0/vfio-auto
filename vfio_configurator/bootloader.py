"""Bootloader detection and kernel parameter configuration."""

import os
import re
import shutil
from pathlib import Path
from typing import Dict, Optional, List, Tuple, Any

from .utils import (
    log_info, log_success, log_warning, log_error, log_debug,
    cached_result, run_command, create_timestamped_backup, get_distro_info
)


@cached_result('kernel_cmdline')
def get_kernel_cmdline() -> str:
    """Get the kernel command line parameters."""
    try:
        return Path("/proc/cmdline").read_text().strip()
    except Exception as e:
        log_error(f"Failed to read kernel command line: {str(e)}")
        return ""


@cached_result('bootloader')
def detect_bootloader() -> str:
    """Detect the bootloader used by the system."""
    # Use distro_info to help with bootloader detection
    distro_info = get_distro_info()
    distro_id = distro_info.get('id', '').lower()
    
    # Check for GRUB
    if os.path.exists('/etc/default/grub'):
        if shutil.which('update-grub'):
            return "grub-debian"  # Debian/Ubuntu style
        elif shutil.which('grub2-mkconfig'):
            return "grub-fedora"  # Fedora/RHEL style
        elif shutil.which('grub-mkconfig'):
            return "grub-arch"    # Arch style
        else:
            # Use distro info as a fallback for identifying grub variant
            if distro_id in ('ubuntu', 'debian', 'linuxmint', 'pop'):
                return "grub-debian"
            elif distro_id in ('fedora', 'rhel', 'centos', 'rocky', 'alma'):
                return "grub-fedora"
            elif distro_id in ('arch', 'manjaro', 'endeavouros'):
                return "grub-arch"
            else:
                return "grub-unknown"

    # Check for systemd-boot
    if os.path.exists('/boot/efi/loader/loader.conf') or os.path.exists('/boot/loader/loader.conf'):
        # Check specifically for Pop!_OS
        if distro_id == 'pop':
            return "systemd-boot-popos"
        else:
            return "systemd-boot"

    # Check for LILO
    if os.path.exists('/etc/lilo.conf'):
        return "lilo"

    return "unknown"


def get_grub_cmdline_params(grub_default_path: Path, debug: bool = False) -> str:
    """Extract current parameters from GRUB_CMDLINE_LINUX_DEFAULT."""
    if not grub_default_path.exists():
        log_warning(f"{grub_default_path} not found. Assuming default 'quiet splash'.")
        return "quiet splash"

    try:
        grub_content = grub_default_path.read_text()
        # Find the GRUB_CMDLINE_LINUX_DEFAULT line, handle variations in spacing/quotes
        match = re.search(r'^\s*GRUB_CMDLINE_LINUX_DEFAULT\s*=\s*(["\'])(.*?)\1', grub_content, re.MULTILINE)
        if not match:
            log_warning(f"Could not find GRUB_CMDLINE_LINUX_DEFAULT in {grub_default_path}. Assuming 'quiet splash'.")
            return "quiet splash"

        params = match.group(2)
        log_debug(f"Found existing GRUB_CMDLINE_LINUX_DEFAULT: \"{params}\"", debug)
        return params

    except Exception as e:
        log_error(f"Error reading {grub_default_path}: {e}")
        return "quiet splash"


def modify_grub_default(params_to_add: List[str], dry_run: bool = False, debug: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Modify GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub to add kernel parameters.

    Args:
        params_to_add: List of kernel parameters to add
        dry_run: If True, don't actually modify files
        debug: If True, print additional debug information

    Returns:
        Tuple[bool, Optional[str]]: (success_status, backup_path)
    """
    log_info("Configuring kernel parameters via /etc/default/grub...")
    grub_default_path = Path('/etc/default/grub')
    backup_path: Optional[str] = None
    modified = False

    if not grub_default_path.exists():
        log_error(f"{grub_default_path} not found. Cannot configure GRUB.")
        return False, None

    # Create backup before modification
    backup_path = create_timestamped_backup(str(grub_default_path), dry_run, debug)
    if not backup_path and not dry_run and grub_default_path.exists():  # Check exists again in case of race
        log_error(f"Failed to create backup of {grub_default_path}. Aborting GRUB modification.")
        return False, None
    elif dry_run and backup_path:
        log_debug(f"[DRY RUN] Backup would be created at {backup_path}", debug)

    if dry_run:
        current_params_str = get_grub_cmdline_params(grub_default_path, debug)
        current_params = set(current_params_str.split())
        new_params_to_add_set = set(params_to_add)
        param_prefixes_to_replace = {p.split('=')[0] for p in params_to_add if '=' in p} | \
                                   {p for p in params_to_add if '=' not in p}
        filtered_current_params = {
            p for p in current_params
            if p.split('=')[0] not in param_prefixes_to_replace and p not in param_prefixes_to_replace
        }
        final_params_set = filtered_current_params.union(new_params_to_add_set)
        final_params_str = " ".join(sorted(list(final_params_set)))

        log_debug(f"[DRY RUN] Would modify {grub_default_path}:", debug)
        log_debug(f"[DRY RUN]   Current params: \"{current_params_str}\"", debug)
        log_debug(f"[DRY RUN]   Params to add: {params_to_add}", debug)
        log_debug(f"[DRY RUN]   Resulting params: \"{final_params_str}\"", debug)
        # Simulate success, return the path where backup *would* be
        return True, backup_path

    try:
        original_content = grub_default_path.read_text()
        # Find the GRUB_CMDLINE_LINUX_DEFAULT line
        cmdline_regex = r'(^\s*GRUB_CMDLINE_LINUX_DEFAULT\s*=\s*(["\']))(.*?)(\2)'
        match = re.search(cmdline_regex, original_content, re.MULTILINE)

        if not match:
            log_error(f"Could not find GRUB_CMDLINE_LINUX_DEFAULT line in {grub_default_path}.")
            # Attempt to restore backup
            if backup_path and Path(backup_path).exists():
                shutil.move(backup_path, str(grub_default_path))
            return False, backup_path  # Return backup path even on failure here

        prefix = match.group(1)  # e.g., GRUB_CMDLINE_LINUX_DEFAULT="
        current_params_str = match.group(3)  # e.g., quiet splash
        suffix = match.group(4)  # e.g., "

        # Parse existing parameters and parameters to add
        current_params = set(current_params_str.split())
        new_params_to_add_set = set(params_to_add)

        # Remove any existing parameters that conflict with new ones (e.g., different iommu= setting)
        param_prefixes_to_replace = {p.split('=')[0] for p in params_to_add if '=' in p} | \
                                   {p for p in params_to_add if '=' not in p}  # Handle simple flags too

        filtered_current_params = set()
        removed_params = set()
        for p in current_params:
            p_key = p.split('=')[0]
            # Check if key matches a key being added, or if the exact param matches a flag being added
            if p_key in param_prefixes_to_replace or p in param_prefixes_to_replace:
                removed_params.add(p)
            else:
                filtered_current_params.add(p)

        if removed_params:
            log_debug(f"Removing conflicting/superseded params: {', '.join(sorted(list(removed_params)))}", debug)

        # Combine filtered existing params with the new ones
        final_params_set = filtered_current_params.union(new_params_to_add_set)
        # Sort alphabetically for consistency and better diffing
        final_params_str = " ".join(sorted(list(final_params_set)))

        # Construct the new line
        new_cmdline_line = f"{prefix}{final_params_str}{suffix}"
        original_cmdline_line = match.group(0)  # The whole matched line

        if new_cmdline_line != original_cmdline_line:
            log_info(f"Updating GRUB_CMDLINE_LINUX_DEFAULT to: \"{final_params_str}\"")
            modified = True

            # Replace the line in the content using the matched start/end positions
            start, end = match.span(0)
            new_content = original_content[:start] + new_cmdline_line + original_content[end:]

            # Write the modified content back
            grub_default_path.write_text(new_content)
            log_success(f"Successfully updated {grub_default_path}.")
        else:
            log_info(f"{grub_default_path} GRUB_CMDLINE_LINUX_DEFAULT is already up-to-date.")
            modified = False  # Explicitly set modified to false

        return True, backup_path  # Return success and the actual backup path

    except Exception as e:
        log_error(f"Failed to modify {grub_default_path}: {e}")
        # Attempt to restore backup
        if backup_path and Path(backup_path).exists():
            try:
                shutil.move(backup_path, str(grub_default_path))
                log_info(f"Restored backup of {grub_default_path} from {backup_path}")
            except Exception as restore_e:
                log_error(f"Failed to restore backup {backup_path}: {restore_e}")
        return False, backup_path  # Return failure and backup path


def configure_kernel_parameters_popos(params_to_add: List[str], dry_run: bool = False, debug: bool = False) -> List[str]:
    """
    Configure kernel parameters using kernelstub on Pop!_OS.
    
    Args:
        params_to_add: List of kernel parameters to add
        dry_run: If True, don't actually modify kernel parameters
        debug: If True, print additional debug information
        
    Returns:
        List[str]: List of parameters actually added
    """
    log_info("Configuring kernel parameters for Pop!_OS using kernelstub...")

    kernelstub_path = shutil.which("kernelstub")
    if not kernelstub_path:
        log_error("kernelstub command not found. Cannot configure kernel parameters on Pop!_OS.")
        return []  # Return empty list indicating failure/no additions

    # Get current parameters - use sudo explicitly in the command passed to run_command
    kernelstub_print_cmd = f"sudo {kernelstub_path} -p"
    # Pass dry_run=False even in dry run mode for read commands
    current_params_output = run_command(kernelstub_print_cmd, dry_run=False, debug=debug)

    if current_params_output is None:
        log_error(f"Failed to get current kernel parameters using: '{kernelstub_print_cmd}'")
        # Try to proceed assuming empty current params, but warn heavily
        current_params = []
        log_warning("Assuming no current kernelstub parameters due to fetch failure.")
    else:
        current_params: List[str] = []
        # Attempt to parse output - look for lines starting with '        options '
        in_options = False
        for line in current_params_output.splitlines():
            stripped_line = line.strip()
            if stripped_line.startswith("Kernel Boot Options:"):
                in_options = True
            elif in_options and stripped_line.startswith("options "):
                # Extract options part
                options_part = stripped_line.replace("options ", "").strip()
                # Split by spaces but preserve quoted parts
                current_params = options_part.split()
                break
        if not current_params:
            log_warning("Could not parse kernel parameters from kernelstub -p output.")
            log_debug(f"kernelstub -p output was:\n{current_params_output}", debug)

    # Determine which parameters need adding/replacing
    params_already_present = set()
    params_to_actually_add = []
    params_to_remove = []  # Params to remove if value changes
    current_params_set = set(current_params)
    current_param_keys = {p.split('=')[0] for p in current_params if '=' in p}

    for param in params_to_add:
        param_key = param.split('=')[0] if '=' in param else param
        is_flag = '=' not in param

        # Check if the exact parameter already exists
        if param in current_params_set:
            params_already_present.add(param)
            log_debug(f"Parameter '{param}' already exists exactly.", debug)
            continue

        # Check if a parameter with the same key but different value exists
        conflicting_param = None
        if not is_flag and param_key in current_param_keys:
            conflicting_params = [p for p in current_params if p.startswith(f"{param_key}=") and p != param]
            if conflicting_params:
                conflicting_param = conflicting_params[0]
                log_info(f"Found conflicting parameter '{conflicting_param}', will replace with '{param}'")
                params_to_remove.append(conflicting_param)

        if conflicting_param:
            params_to_actually_add.append(param)  # Add the replacement
        elif param_key in current_param_keys and is_flag:
            # Flag is already covered by a param=value setting, skip
            log_debug(f"Flag '{param}' has corresponding parameter with value, skipping.", debug)
        elif param not in current_params_set:
            params_to_actually_add.append(param)  # Completely new parameter

    if params_already_present:
        log_info(f"Kernel parameters already present: {', '.join(sorted(list(params_already_present)))}")

    if not params_to_actually_add and not params_to_remove:
        log_info("No kernel parameters need to be added or changed via kernelstub.")
        return []  # Nothing was added or changed

    # --- Execution Phase ---
    added_params_successfully = []
    removed_params_successfully = []

    # Remove conflicting parameters first
    if params_to_remove:
        log_info(f"Parameters to remove via kernelstub: {', '.join(params_to_remove)}")
        if dry_run:
            log_debug(f"[DRY RUN] Would remove parameters via kernelstub: {params_to_remove}", debug)
            removed_params_successfully = params_to_remove  # Assume success in dry run
        else:
            for param in params_to_remove:
                cmd = f"sudo {kernelstub_path} -d \"{param}\""
                result = run_command(cmd, dry_run=False, debug=debug)
                if result is not None:
                    log_success(f"Removed kernel parameter: {param}")
                    removed_params_successfully.append(param)
                else:
                    log_error(f"Failed to remove kernel parameter: {param}")

    # Add the new/updated parameters
    if params_to_actually_add:
        log_info(f"Parameters to add via kernelstub: {', '.join(params_to_actually_add)}")
        if dry_run:
            log_debug(f"[DRY RUN] Would add parameters via kernelstub: {params_to_actually_add}", debug)
            added_params_successfully = params_to_actually_add  # Assume success in dry run
        else:
            for param in params_to_actually_add:
                cmd = f"sudo {kernelstub_path} -a \"{param}\""
                result = run_command(cmd, dry_run=False, debug=debug)
                if result is not None:
                    log_success(f"Added kernel parameter: {param}")
                    added_params_successfully.append(param)
                else:
                    log_error(f"Failed to add kernel parameter: {param}")

    # Log final status
    if added_params_successfully:
        log_success(f"Added/Updated {len(added_params_successfully)} kernel parameters with kernelstub.")
    if removed_params_successfully:
        log_success(f"Removed {len(removed_params_successfully)} conflicting kernel parameters with kernelstub.")

    if not added_params_successfully and params_to_actually_add:
        log_error("Attempted to add parameters, but none were added successfully.")
    if not removed_params_successfully and params_to_remove:
        log_error("Attempted to remove parameters, but none were removed successfully.")

    return added_params_successfully  # Return only the parameters that were newly added/updated


def configure_kernel_parameters(dry_run: bool = False, debug: bool = False) -> Optional[Dict[str, Any]]:
    """
    Configure kernel parameters for IOMMU and VFIO using the appropriate method.

    Args:
        dry_run: If True, don't actually modify kernel parameters
        debug: If True, print additional debug information

    Returns:
        A dictionary containing info about the operation, e.g.,
        {'status': bool, 'method': 'grub'|'kernelstub'|'manual', 'backup_path': Optional[str], 'added_params': List[str]}
        Returns None on critical failure.
    """
    log_info("Configuring kernel parameters for IOMMU and VFIO...")
    bootloader = detect_bootloader()
    log_info(f"Detected bootloader: {bootloader}")

    # Determine required parameters
    from .checks import is_amd_cpu
    cpu_is_amd = is_amd_cpu()  # Use cached check
    iommu_param = "amd_iommu=on" if cpu_is_amd else "intel_iommu=on"
    # rd.driver.pre=vfio-pci forces vfio-pci to load before graphics drivers in initramfs
    required_params = [iommu_param, "iommu=pt", "rd.driver.pre=vfio-pci"]
    log_info(f"Required kernel parameters: {' '.join(required_params)}")

    result_info = {'status': False, 'method': 'unknown', 'backup_path': None, 'added_params': []}

    # --- GRUB ---
    if "grub" in bootloader:
        log_info("Using GRUB configuration method")
        result_info['method'] = 'grub'
        success, backup_path = modify_grub_default(required_params, dry_run, debug)
        result_info['status'] = success
        result_info['backup_path'] = backup_path
        
        # Run update-grub or equivalent
        if success:
            update_cmd = None
            if bootloader == "grub-debian":
                update_cmd = "sudo update-grub"
            elif bootloader == "grub-fedora":
                update_cmd = "sudo grub2-mkconfig -o /boot/grub2/grub.cfg"
            elif bootloader == "grub-arch":
                update_cmd = "sudo grub-mkconfig -o /boot/grub/grub.cfg"
            else:
                # Fallback for unknown GRUB variants
                if shutil.which("update-grub"):
                    update_cmd = "sudo update-grub"
                elif shutil.which("grub2-mkconfig"):
                    update_cmd = "sudo grub2-mkconfig -o /boot/grub2/grub.cfg"
                elif shutil.which("grub-mkconfig"):
                    update_cmd = "sudo grub-mkconfig -o /boot/grub/grub.cfg"
                    
            if update_cmd:
                log_info(f"Updating GRUB configuration using: {update_cmd}")
                if dry_run:
                    log_debug(f"[DRY RUN] Would run: {update_cmd}", debug)
                    result_info['added_params'] = required_params  # Assume all were added in dry run
                else:
                    update_result = run_command(update_cmd, dry_run=False, debug=debug)
                    if update_result is not None:
                        log_success("GRUB configuration updated successfully")
                        result_info['added_params'] = required_params  # Assume all were added
                    else:
                        log_error("Failed to update GRUB configuration")
                        result_info['status'] = False  # Set status to failure
            else:
                log_error("Could not determine appropriate GRUB update command")
                log_warning("You may need to manually update your GRUB configuration with 'update-grub' or equivalent")
                result_info['status'] = False
                
    elif bootloader == "systemd-boot-popos":
        log_info("Using Pop!_OS kernelstub configuration method")
        result_info['method'] = 'kernelstub'
        added_params = configure_kernel_parameters_popos(required_params, dry_run, debug)
        result_info['status'] = bool(added_params) or all(p in added_params for p in required_params)
        result_info['added_params'] = added_params
        
    else:
        log_warning(f"Unsupported bootloader: {bootloader}")
        log_warning("You will need to manually add these kernel parameters:")
        for param in required_params:
            log_info(f"  {param}")
        log_warning("Please consult your distribution's documentation for adding kernel parameters.")
        result_info['method'] = 'manual'
        result_info['status'] = False
        
    return result_info