#!/usr/bin/env python3
"""Cleanup functionality for VFIO configuration."""

import datetime
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple

from .utils import log_info, log_success, log_warning, log_error, log_debug, run_command


def create_cleanup_script(output_dir: str, changes: Dict[str, List[Dict[str, Any]]], dry_run: bool = False, debug: bool = False) -> Optional[str]:
    """Create a shell script to revert the changes recorded.
    
    Args:
        output_dir: Directory to write the cleanup script
        changes: Dictionary of recorded changes made by VFIO setup
        dry_run: If True, don't actually write the script
        debug: If True, print additional debug information
    
    Returns:
        Path to the created script, or None if creation failed
    """
    log_info("Generating cleanup script...")
    script_path = Path(output_dir) / "vfio_cleanup.sh"
    script_path_str = str(script_path)

    # Detect the most likely restoration commands based on distro
    distro_info = _detect_distro(debug)
    
    # --- Script Header & Helper Functions ---
    script_content = _generate_script_header(distro_info)
    
    # --- Process All Changes ---
    # Organize changes by type for proper ordering
    file_changes = changes.get("files", [])
    kernelstub_changes = changes.get("kernelstub", [])
    btrfs_changes = changes.get("btrfs", [])
    modules_changes = changes.get("modules", [])
    
    # --- File Restoration ---
    file_restoration_content = _generate_file_restoration(file_changes)
    script_content.extend(file_restoration_content)
    
    # --- Kernel Parameter Removal ---
    kernel_params_content, kernelstub_params, grub_modified = _generate_kernel_param_restoration(
        kernelstub_changes, file_changes, distro_info
    )
    script_content.extend(kernel_params_content)
    
    # --- Module Configuration Cleanup ---
    modules_content, modules_modified = _generate_module_cleanup(file_changes, modules_changes, distro_info)
    script_content.extend(modules_content)
    
    # --- Update Initramfs ---
    # Should run after module configs are reverted
    initramfs_content = _generate_initramfs_update(
        modules_modified=modules_modified, 
        grub_modified=grub_modified,
        distro_info=distro_info,
        debug=debug
    )
    script_content.extend(initramfs_content)
    
    # --- Update Bootloader Config ---
    # Should run after /etc/default/grub is potentially restored and initramfs updated
    bootloader_content = _generate_bootloader_update(grub_modified, distro_info)
    script_content.extend(bootloader_content)
    
    # --- BTRFS Snapshot Info ---
    btrfs_content = _generate_btrfs_info(btrfs_changes)
    script_content.extend(btrfs_content)
    
    # --- Final Verification ---
    script_content.extend(_generate_verification_steps())
    
    # --- Final Messages ---
    script_content.extend(_generate_final_messages())

    # --- Write Script ---
    final_script_content = "\n".join(script_content)
    if dry_run:
        log_debug(f"[DRY RUN] Would create cleanup script at {script_path_str}", debug)
        if debug:
            log_debug(f"Script content sample:\n{final_script_content[:500]}...\n(truncated)", debug)
        log_success("[DRY RUN] Cleanup script generation simulated.")
        return script_path_str  # Return the intended path

    try:
        script_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure output dir exists
        script_path.write_text(final_script_content)
        os.chmod(script_path_str, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)  # 0o755
        log_success(f"Cleanup script created: {script_path_str}")
        log_info("Review the cleanup script carefully before running it with 'sudo bash ...'")
        return script_path_str
    except Exception as e:
        log_error(f"Failed to write cleanup script to {script_path_str}: {e}")
        return None


def _detect_distro(debug: bool = False) -> Dict[str, Any]:
    """Detect the current distribution and commands for restoration.
    
    Returns:
        Dict containing distribution info and appropriate commands
    """
    distro_info = {
        "name": "unknown",
        "family": "unknown",
        "bootloader": "unknown",
        "initramfs_update_cmd": "",
        "is_debian": False,
        "is_fedora": False,
        "is_arch": False,
        "is_suse": False,
        "has_kernelstub": False,
        "dracut_conf_dir": "/etc/dracut.conf.d",
        "mkinitcpio_conf": "/etc/mkinitcpio.conf",
    }
    
    # Check for specific distribution files
    if os.path.exists("/etc/debian_version"):
        distro_info["name"] = "Debian/Ubuntu"
        distro_info["family"] = "debian"
        distro_info["is_debian"] = True
        distro_info["bootloader"] = "grub"
        distro_info["initramfs_update_cmd"] = "update-initramfs -u"
    elif os.path.exists("/etc/fedora-release"):
        distro_info["name"] = "Fedora"
        distro_info["family"] = "fedora"
        distro_info["is_fedora"] = True
        distro_info["bootloader"] = "grub2"
        distro_info["initramfs_update_cmd"] = "dracut --force"
    elif os.path.exists("/etc/arch-release"):
        distro_info["name"] = "Arch Linux"
        distro_info["family"] = "arch"
        distro_info["is_arch"] = True
        distro_info["bootloader"] = "grub"
        distro_info["initramfs_update_cmd"] = "mkinitcpio -P"
    elif os.path.exists("/etc/SuSE-release") or os.path.exists("/etc/suse-release"):
        distro_info["name"] = "SUSE"
        distro_info["family"] = "suse"
        distro_info["is_suse"] = True
        distro_info["bootloader"] = "grub2"
        distro_info["initramfs_update_cmd"] = "mkinitrd"
    
    # Look for kernelstub for Pop!_OS
    if shutil.which("kernelstub"):
        distro_info["has_kernelstub"] = True
        if "System76" in run_command("lsb_release -a", debug=debug) or "Pop!_OS" in run_command("lsb_release -a", debug=debug):
            distro_info["name"] = "Pop!_OS"
            distro_info["family"] = "debian"
            distro_info["bootloader"] = "systemd-boot-popos"
    
    # Detect bootloader if not already determined
    if distro_info["bootloader"] == "unknown":
        if os.path.exists("/boot/grub/grub.cfg"):
            distro_info["bootloader"] = "grub"
        elif os.path.exists("/boot/grub2/grub.cfg"):
            distro_info["bootloader"] = "grub2"
        elif os.path.exists("/boot/efi/EFI/BOOT/BOOTX64.EFI") and os.path.exists("/boot/efi/loader/loader.conf"):
            distro_info["bootloader"] = "systemd-boot"
    
    return distro_info


def _generate_script_header(distro_info: Dict[str, Any]) -> List[str]:
    """Generate the script header with helper functions."""
    return [
        "#!/bin/bash",
        "# VFIO Setup Cleanup Script",
        f"# Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# Detected distribution: {distro_info['name']}",
        "# This script attempts to revert changes made by the VFIO setup script.",
        "# WARNING: Review this script carefully before running.",
        "# WARNING: Use BTRFS snapshot restoration for the most reliable rollback if available.",
        "",
        "# --- Configuration ---",
        "# Set to 'true' to simulate actions without making changes",
        "DRY_RUN=false # Change to true for simulation",
        "# Set to 'true' to include extra diagnostic information",
        "VERBOSE=false # Change to true for extra output",
        "",
        "# --- Color Definitions ---",
        "RED='\\033[0;31m'",
        "GREEN='\\033[0;32m'",
        "YELLOW='\\033[0;33m'",
        "BLUE='\\033[0;34m'",
        "NC='\\033[0m' # No Color",
        "",
        "set -e # Exit on first error (use '|| true' for non-critical steps)",
        "set -o pipefail # Ensure pipeline errors are caught",
        "",
        "echo -e \"${BLUE}=== VFIO Setup Cleanup ===${NC}\"",
        "",
        "# --- Helper Functions ---",
        "log_info() { echo -e \"${BLUE}[INFO]${NC} $*\"; }",
        "log_success() { echo -e \"${GREEN}[SUCCESS]${NC} $*\"; }",
        "log_warn() { echo -e \"${YELLOW}[WARNING]${NC} $*\"; }",
        "log_error() { echo -e \"${RED}[ERROR]${NC} $*\"; }",
        "log_debug() {",
        "  if [ \"$VERBOSE\" = true ]; then",
        "    echo -e \"[DEBUG] $*\"",
        "  fi",
        "}",
        "",
        "run_cmd() {",
        "  log_info \"Executing: $*\"",
        "  if [ \"$DRY_RUN\" = true ]; then",
        "    log_warn \"[DRY RUN] Would execute: $*\"",
        "    return 0 # Simulate success in dry run",
        "  fi",
        "  # Use eval carefully, ensure commands are safe",
        "  eval \"$@\"",
        "  local exit_code=$?",
        "  if [ $exit_code -ne 0 ]; then",
        "    log_error \"Command failed with exit code $exit_code: $*\"",
        "  else",
        "    log_debug \"Command completed successfully: $*\"",
        "  fi",
        "  return $exit_code",
        "}",
        "",
        "check_root() {",
        "  if [ \"$(id -u)\" -ne 0 ]; then",
        "    log_error 'This script must be run as root (sudo).' >&2",
        "    exit 1",
        "  fi",
        "}",
        "",
        "backup_file() {",
        "  local original=$1",
        "  local backup=\"${original}.bak.$(date +%Y%m%d-%H%M%S)\"",
        "  if [ -e \"$original\" ]; then",
        "    log_debug \"Creating backup of $original to $backup\"",
        "    if [ \"$DRY_RUN\" = true ]; then",
        "      log_warn \"[DRY RUN] Would create backup: $backup\"",
        "    else",
        "      cp -f \"$original\" \"$backup\"",
        "    fi",
        "    echo \"$backup\"",
        "  else",
        "    echo \"\"",
        "  fi",
        "}",
        "",
        "# --- Function to handle special directories ---",
        "remove_empty_dir_if_created() {",
        "  local dir=$1",
        "  local was_created=${2:-false}",
        "  if [ \"$was_created\" = true ] && [ -d \"$dir\" ] && [ -z \"$(ls -A \"$dir\")\" ]; then",
        "    log_info \"Removing empty directory that was created: $dir\"",
        "    run_cmd rmdir \"$dir\" || log_warn \"Could not remove directory: $dir\"",
        "  fi",
        "}",
        "",
        "# --- Start Execution ---",
        "check_root",
        "log_info \"Checking script settings: DRY_RUN=$DRY_RUN, VERBOSE=$VERBOSE\"",
        "log_info \"Starting cleanup process...\"",
        "",
    ]


def _generate_file_restoration(file_changes: List[Dict[str, Any]]) -> List[str]:
    """Generate script content for restoring files."""
    if not file_changes:
        return ["# No file changes to revert."]
        
    script_content = ["# --- Reverting File Changes ---"]
    restored_files = set()

    # Iterate through changes in reverse order for potentially better restoration logic
    for change in reversed(file_changes):
        item = change.get('item')
        action = change.get('action')
        details = change.get('details', {})
        backup_path = details.get('backup_path') if isinstance(details, dict) else None

        if not item or item in restored_files:
            continue

        if action == "created":
            script_content.extend([
                f"log_info 'Removing created file: {item}'",
                f"if [ -e \"{item}\" ]; then",
                f"  run_cmd rm -f \"{item}\"",
                f"else",
                f"  log_warn 'File {item} does not exist, nothing to remove.'",
                f"fi"
            ])
            
            # Check if we need to remove parent directory if it was created and is empty
            if details and details.get('created_dir'):
                parent_dir = os.path.dirname(item)
                script_content.extend([
                    f"# Check if parent directory is empty and remove if created by the setup",
                    f"remove_empty_dir_if_created \"{parent_dir}\" true"
                ])
                
            restored_files.add(item)
            
        elif action == "modified" and backup_path:
            script_content.extend([
                f"log_info 'Restoring backup for: {item}'",
                f"if [ -e \"{backup_path}\" ]; then",
                f"  # Create a new backup of the current version just in case",
                f"  current_backup=$(backup_file \"{item}\")",
                f"  if [ -n \"$current_backup\" ]; then",
                f"    log_info \"Created backup of current file: $current_backup\"",
                f"  fi",
                f"  run_cmd cp -f \"{backup_path}\" \"{item}\"",
                f"  log_success 'Restored {item} from backup {backup_path}'",
                f"else",
                f"  log_warn 'Backup file {backup_path} not found. Cannot restore {item}.'",
                f"fi"
            ])
            restored_files.add(item)
            
        elif action == "modified":
            script_content.extend([
                f"log_warn 'No backup available for modified file: {item}'",
                f"log_warn 'Manual restoration may be required for: {item}'"
            ])
            restored_files.add(item)
            
    script_content.append("")
    return script_content


def _generate_kernel_param_restoration(
    kernelstub_changes: List[Dict[str, Any]],
    file_changes: List[Dict[str, Any]],
    distro_info: Dict[str, Any]
) -> Tuple[List[str], List[str], bool]:
    """Generate script content for restoring kernel parameters.
    
    Returns:
        Tuple of (script_content, kernelstub_params, grub_modified)
    """
    script_content = []
    kernelstub_params = []
    
    # Check if /etc/default/grub was modified for GRUB systems
    grub_modified = False
    grub_default_file = '/etc/default/grub'
    
    # Check for GRUB modifications
    for change in file_changes:
        if change.get('item') == grub_default_file and change.get('action') == 'modified':
            grub_modified = True
            break
    
    # --- Kernelstub Parameter Removal (Pop!_OS) ---
    for change in kernelstub_changes:
        if change.get('action') == 'added':
            param = change.get('item', '')
            if param:
                kernelstub_params.append(param)
    
    if kernelstub_params:
        script_content.append("# --- Removing Kernel Parameters (kernelstub - Pop!_OS) ---")
        script_content.append("if command -v kernelstub >/dev/null 2>&1; then")
        script_content.append("  log_info 'Attempting to remove kernel parameters via kernelstub...'")
        for param in sorted(list(kernelstub_params)):
            script_content.append(f"  run_cmd kernelstub --delete-options \"{param}\" || log_warn 'Failed to remove parameter: {param}'")
        script_content.append("  log_info 'Running kernelstub to apply changes...'")
        script_content.append("  run_cmd kernelstub")
        script_content.append("else")
        script_content.append("  log_warn 'kernelstub command not found. Cannot remove parameters automatically.'")
        script_content.append("  log_warn 'You may need to manually remove these parameters from your boot configuration:'")
        for param in sorted(list(kernelstub_params)):
            script_content.append(f"  log_warn '  - {param}'")
        script_content.append("fi")
        script_content.append("")
    elif distro_info["has_kernelstub"]:
        script_content.append("# No kernelstub parameters to remove.")
        script_content.append("")
    
    return script_content, kernelstub_params, grub_modified


def _generate_module_cleanup(
    file_changes: List[Dict[str, Any]], 
    modules_changes: List[Dict[str, Any]],
    distro_info: Dict[str, Any]
) -> Tuple[List[str], bool]:
    """Generate script content for cleaning up module configurations.
    
    Returns:
        Tuple of (script_content, modules_modified)
    """
    script_content = ["# --- Cleaning Module Configurations ---"]
    modules_modified = False
    
    # Check if VFIO modules config files were modified
    vfio_conf = '/etc/modprobe.d/vfio.conf'
    vfio_load_conf = '/etc/modules-load.d/vfio-pci-load.conf'
    dracut_vfio_conf = '/etc/dracut.conf.d/vfio.conf'
    booster_vfio_conf = '/etc/booster.d/vfio.conf'
    
    vfio_conf_files = [vfio_conf, vfio_load_conf, dracut_vfio_conf, booster_vfio_conf]
    
    for change in file_changes:
        if change.get('item') in vfio_conf_files:
            modules_modified = True
            break
    
    if modules_modified:
        script_content.extend([
            "log_info 'Checking for VFIO module configurations to remove...'",
            "",
            "# Check and remove modprobe configuration",
            f"if [ -f \"{vfio_conf}\" ]; then",
            f"  log_info 'Removing VFIO modprobe configuration: {vfio_conf}'",
            f"  run_cmd rm -f \"{vfio_conf}\"",
            f"fi",
            "",
            "# Check and remove modules-load configuration",
            f"if [ -f \"{vfio_load_conf}\" ]; then",
            f"  log_info 'Removing VFIO modules-load configuration: {vfio_load_conf}'",
            f"  run_cmd rm -f \"{vfio_load_conf}\"",
            f"fi",
            "",
            "# Check and remove dracut configuration",
            f"if [ -f \"{dracut_vfio_conf}\" ]; then",
            f"  log_info 'Removing VFIO dracut configuration: {dracut_vfio_conf}'",
            f"  run_cmd rm -f \"{dracut_vfio_conf}\"",
            f"fi",
            "",
            "# Check and remove booster configuration",
            f"if [ -f \"{booster_vfio_conf}\" ]; then",
            f"  log_info 'Removing VFIO booster configuration: {booster_vfio_conf}'",
            f"  run_cmd rm -f \"{booster_vfio_conf}\"",
            f"fi",
            "",
            "# Check for empty directories to clean up",
            "remove_empty_dir_if_created \"/etc/modprobe.d\" false",
            "remove_empty_dir_if_created \"/etc/modules-load.d\" false",
            "remove_empty_dir_if_created \"/etc/dracut.conf.d\" false",
            "remove_empty_dir_if_created \"/etc/booster.d\" false",
            ""
        ])
    else:
        script_content.append("# No module configurations need to be removed.")
        script_content.append("")
    
    return script_content, modules_modified


def _generate_initramfs_update(
    modules_modified: bool, 
    grub_modified: bool, 
    distro_info: Dict[str, Any],
    debug: bool
) -> List[str]:
    """Generate script content for updating initramfs."""
    script_content = ["# --- Updating Initramfs ---"]
    
    if not (modules_modified or grub_modified):
        script_content.extend([
            "log_info 'No initramfs-related changes detected, skipping update.'",
            ""
        ])
        return script_content
    
    script_content.append("log_info 'Updating initramfs to apply configuration changes...'")
    
    # Use distribution-specific initramfs update command if available
    if distro_info["initramfs_update_cmd"]:
        script_content.extend([
            f"if command -v {distro_info['initramfs_update_cmd'].split()[0]} >/dev/null 2>&1; then",
            f"  run_cmd {distro_info['initramfs_update_cmd']}",
            "else"
        ])
    else:
        script_content.append("# No distribution-specific initramfs command detected, trying common methods")
    
    # Fall back to common methods if distribution-specific command isn't available
    script_content.extend([
        "  # Try common initramfs update methods",
        "  if command -v update-initramfs >/dev/null 2>&1; then",
        "    log_info 'Using update-initramfs (Debian/Ubuntu)'",
        "    run_cmd update-initramfs -u",
        "  elif command -v dracut >/dev/null 2>&1; then",
        "    log_info 'Using dracut (Fedora/RHEL)'",
        "    run_cmd dracut --force",
        "  elif command -v mkinitcpio >/dev/null 2>&1; then",
        "    log_info 'Using mkinitcpio (Arch)'",
        "    run_cmd mkinitcpio -P",
        "  elif command -v mkinitrd >/dev/null 2>&1; then",
        "    log_info 'Using mkinitrd (SUSE)'",
        "    run_cmd mkinitrd",
        "  elif command -v booster >/dev/null 2>&1; then",
        "    log_info 'Using booster (modern distros)'",
        "    run_cmd booster build",
        "  else",
        "    log_warn 'Could not find an appropriate initramfs update command.'",
        "    log_warn 'You may need to manually update your initramfs.'",
        "  fi"
    ])
    
    if distro_info["initramfs_update_cmd"]:
        script_content.append("fi")
    
    script_content.append("")
    return script_content


def _generate_bootloader_update(grub_modified: bool, distro_info: Dict[str, Any]) -> List[str]:
    """Generate script content for updating bootloader."""
    script_content = ["# --- Updating Bootloader Configuration ---"]
    
    # We should always check for systemd-boot if that's the detected bootloader
    systemd_boot_detected = distro_info["bootloader"] in ["systemd-boot", "systemd-boot-popos"]
    
    if not grub_modified and not systemd_boot_detected:
        script_content.extend([
            "log_info 'No bootloader configuration changes detected, skipping update.'",
            ""
        ])
        return script_content
    
    bootloader = distro_info["bootloader"]
    
    if bootloader.startswith("grub"):
        script_content.extend([
            "log_info 'Updating GRUB bootloader configuration...'",
            "# Try to find the appropriate GRUB update command",
            "if command -v update-grub >/dev/null 2>&1; then",
            "  log_info 'Using update-grub'",
            "  run_cmd update-grub",
            "elif command -v grub2-mkconfig >/dev/null 2>&1; then",
            "  # Find a valid grub.cfg location",
            "  grub_cfg_found=false",
            "  for cfg_path in /boot/grub2/grub.cfg /boot/grub/grub.cfg /boot/efi/EFI/fedora/grub.cfg; do",
            "    if [ -e \"$cfg_path\" ]; then",
            "      log_info \"Found GRUB config at $cfg_path\"",
            "      run_cmd grub2-mkconfig -o \"$cfg_path\"",
            "      grub_cfg_found=true",
            "      break",
            "    fi",
            "  done",
            "  if [ \"$grub_cfg_found\" = false ]; then",
            "    log_warn 'Could not find a valid grub.cfg location.'",
            "    log_warn 'You may need to manually update your GRUB configuration.'",
            "  fi",
            "elif command -v grub-mkconfig >/dev/null 2>&1; then",
            "  # Find a valid grub.cfg location",
            "  grub_cfg_found=false",
            "  for cfg_path in /boot/grub/grub.cfg /boot/efi/EFI/ubuntu/grub.cfg; do",
            "    if [ -e \"$cfg_path\" ]; then",
            "      log_info \"Found GRUB config at $cfg_path\"",
            "      run_cmd grub-mkconfig -o \"$cfg_path\"",
            "      grub_cfg_found=true",
            "      break",
            "    fi",
            "  done",
            "  if [ \"$grub_cfg_found\" = false ]; then",
            "    log_warn 'Could not find a valid grub.cfg location.'",
            "    log_warn 'You may need to manually update your GRUB configuration.'",
            "  fi",
            "else",
            "  log_warn 'Could not determine appropriate GRUB update command.'",
            "  log_warn 'You may need to manually update your bootloader configuration.'",
            "fi"
        ])
    elif bootloader == "systemd-boot-popos" or bootloader == "systemd-boot":
        script_content.extend([
            "log_info 'Detected systemd-boot bootloader.'",
            "",
            "# Look for systemd-boot backups in both the conventional and project backup directories",
            "PROJECT_ROOT=\"$(dirname \"$0\")\"",
            "BACKUP_DIR=\"${PROJECT_ROOT}/backups\"",
            "",
            "# Restore systemd-boot entry files from backups if they exist",
            "log_info 'Looking for systemd-boot entry backups to restore...'",
            "",
            "# First check in the project backup directory",
            "if [ -d \"${BACKUP_DIR}\" ]; then",
            "  log_info \"Checking for backups in ${BACKUP_DIR}\"",
            "  # Look for files with pattern *boot_loader_entries*.vfio_bak.*",
            "  for backup_file in \"${BACKUP_DIR}\"/*boot_loader_entries*.vfio_bak.*; do",
            "    if [ -f \"$backup_file\" ] && [[ \"$backup_file\" != *\"fallback\"* ]]; then",
            "      # Extract the original filename from backup filename",
            "      original_filename=$(basename \"$backup_file\" | sed 's/.*_\\([^_]*\\.conf\\)\\.vfio_bak.*/\\1/')",
            "      if [[ \"$original_filename\" == *.conf ]]; then",
            "        # Try standard locations for systemd-boot entries",
            "        for entry_dir in /boot/loader/entries /boot/efi/loader/entries /efi/loader/entries; do",
            "          if [ -d \"$entry_dir\" ]; then",
            "            entry_file=\"${entry_dir}/${original_filename}\"",
            "            if [ -f \"$entry_file\" ]; then",
            "              log_info \"Restoring systemd-boot entry from project backup: $backup_file -> $entry_file\"",
            "              run_cmd cp -f \"$backup_file\" \"$entry_file\"",
            "              break",
            "            fi",
            "          fi",
            "        done",
            "      fi",
            "    fi",
            "  done",
            "fi",
            "",
            "# Also check for legacy-style backups next to the original files",
            "log_info 'Checking for legacy backups next to original files'",
            "for file_path in /boot/loader/entries/*.conf /boot/efi/loader/entries/*.conf; do",
            "  if [ -f \"$file_path\" ] && [[ \"$file_path\" != *\"fallback\"* ]]; then",
            "    backup_path=\"${file_path}.vfio_bak.*\"",
            "    if ls $backup_path >/dev/null 2>&1; then",
            "      newest_backup=$(ls -t $backup_path | head -1)",
            "      log_info \"Restoring systemd-boot entry from legacy backup: $newest_backup -> $file_path\"",
            "      run_cmd cp -f \"$newest_backup\" \"$file_path\"",
            "    fi",
            "  fi",
            "done",
            "",
            "# Update systemd-boot configuration",
            "if command -v bootctl >/dev/null 2>&1; then",
            "  log_info 'Updating systemd-boot configuration...'",
            "  run_cmd bootctl update || log_warn 'bootctl update failed'",
            "else",
            "  log_warn 'bootctl command not found. Unable to update systemd-boot.'",
            "fi"
        ])
    else:
        script_content.extend([
            f"log_warn 'Unknown bootloader type: {bootloader}'",
            "log_warn 'You may need to manually update your bootloader configuration.'"
        ])
    
    script_content.append("")
    return script_content


def _generate_btrfs_info(btrfs_changes: List[Dict[str, Any]]) -> List[str]:
    """Generate script content for BTRFS snapshots information."""
    script_content = []
    
    # --- BTRFS Snapshot Info ---
    btrfs_snapshots = []
    for change in btrfs_changes:
        if change.get('action') == 'snapshot':
            snap_path = change.get('item')
            if snap_path:
                btrfs_snapshots.append(snap_path)

    if btrfs_snapshots:
        script_content.extend([
            "# --- BTRFS Snapshot Information ---",
            "log_info 'BTRFS snapshots were created during the VFIO setup:'"
        ])
        
        for i, snap_path in enumerate(btrfs_snapshots):
            script_content.append(f"log_info '  [{i+1}] {snap_path}'")
            
        script_content.extend([
            "",
            "log_info 'To restore from a BTRFS snapshot (recommended method):'",
            "log_info '  1. Boot into recovery mode or a live environment'",
            "log_info '  2. Mount your BTRFS filesystem'",
            "log_info '  3. Use: btrfs subvolume delete /path/to/current/subvolume'",
            "log_info '  4. Use: btrfs subvolume snapshot /path/to/snapshot /path/to/restored/subvolume'",
            ""
        ])
    else:
        script_content.extend([
            "# No BTRFS snapshots were recorded during VFIO setup.",
            ""
        ])
    
    return script_content


def _generate_verification_steps() -> List[str]:
    """Generate verification steps for the end of the cleanup."""
    return [
        "# --- Verification Steps ---",
        "log_info 'Verifying cleanup results...'",
        "",
        "# Check for vfio configuration files",
        "vfio_files_exist=false",
        "for f in /etc/modprobe.d/vfio*.conf /etc/modules-load.d/vfio*.conf; do",
        "  if [ -f \"$f\" ]; then",
        "    vfio_files_exist=true",
        "    log_warn \"VFIO configuration file still exists: $f\"",
        "  fi",
        "done",
        "",
        "if [ \"$vfio_files_exist\" = false ]; then",
        "  log_success 'All VFIO configuration files have been removed.'",
        "fi",
        "",
        "# Check kernel command line for VFIO settings",
        "if grep -q 'vfio\|iommu=pt' /proc/cmdline; then",
        "  log_warn 'VFIO/IOMMU parameters are still present in kernel command line.'",
        "  log_warn 'These will be removed after a reboot if cleanup was successful.'",
        "  log_info 'Current cmdline: '",
        "  cat /proc/cmdline",
        "else",
        "  log_success 'No VFIO/IOMMU settings detected in current kernel command line.'",
        "fi",
        "",
        "# Check VFIO modules",
        "if lsmod | grep -q 'vfio'; then",
        "  log_warn 'VFIO modules are still loaded. These should unload after a reboot.'",
        "  lsmod | grep vfio",
        "else",
        "  log_success 'No VFIO modules currently loaded.'",
        "fi",
        "",
    ]


def _generate_final_messages() -> List[str]:
    """Generate final messages for the cleanup script."""
    return [
        "# --- Final Summary ---",
        "echo",
        "log_success '=== VFIO Setup Cleanup Completed ==='",
        "log_info 'Review the output above for any errors or warnings.'",
        "log_warn 'A SYSTEM REBOOT is REQUIRED to ensure all changes take effect!'",
        "log_info 'After rebooting, your system should no longer have VFIO configured.'",
        "",
        "exit 0"
    ]