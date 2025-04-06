#!/usr/bin/env python3
# filepath: /home/xiao/Documents/source/repo/vfio/vfio_configurator/cleanup.py
"""Cleanup functionality for VFIO configuration."""

import datetime
import os
from pathlib import Path
from typing import Dict, List, Any, Optional

from .utils import log_info, log_success, log_warning, log_error, log_debug


def create_cleanup_script(output_dir: str, changes: Dict[str, List[Dict[str, Any]]], dry_run: bool = False, debug: bool = False) -> Optional[str]:
    """Create a shell script to revert the changes recorded."""
    log_info("Generating cleanup script...")
    script_path = Path(output_dir) / "vfio_cleanup.sh"
    script_path_str = str(script_path)

    # --- Script Header ---
    script_content = [
        "#!/bin/bash",
        "# VFIO Setup Cleanup Script",
        f"# Generated on: {datetime.datetime.now().isoformat()}",
        "# This script attempts to revert changes made by the vfio-lain.py setup script.",
        "# WARNING: Review this script carefully before running.",
        "# WARNING: Use BTRFS snapshot restoration for the most reliable rollback if available.",
        "",
        "# --- Configuration ---",
        "# Set to 'true' to simulate actions without making changes",
        "DRY_RUN=false # Change to true for simulation",
        "",
        "set -e # Exit on first error (use '|| true' for non-critical steps)",
        "set -o pipefail # Ensure pipeline errors are caught",
        "",
        "echo '--- Starting VFIO Setup Cleanup ---'",
        "",
        "# --- Helper Functions ---",
        "log_info() { echo \"[INFO] $*\"; }",
        "log_warn() { echo \"[WARN] $*\"; }",
        "log_error() { echo \"[ERROR] $*\"; }",
        "run_cmd() {",
        "  log_info \"Executing: $*\"",
        "  if [ \"$DRY_RUN\" = true ]; then",
        "    log_warn \"[DRY RUN] Would execute: $*\"",
        "    return 0 # Simulate success in dry run",
        "  fi",
        "  eval \"$@\" # Use eval carefully, ensure commands are safe",
        "  local exit_code=$?",
        "  if [ $exit_code -ne 0 ]; then",
        "    log_error \"Command failed with exit code $exit_code: $*\"",
        "  fi",
        "  return $exit_code",
        "}",
        "check_root() {",
        "  if [ \"$(id -u)\" -ne 0 ]; then",
        "    log_error 'This script must be run as root (sudo).' >&2",
        "    exit 1",
        "  fi",
        "}",
        "",
        "# --- Start Execution ---",
        "check_root",
        "log_info \"Checking DRY_RUN setting: $DRY_RUN\"",
        "",
    ]

    # --- File Restoration ---
    script_content.append("# --- Reverting File Changes ---")
    restored_files = set()
    # Iterate through changes in reverse order for potentially better restoration logic
    for change in reversed(changes.get("files", [])):
        item = change.get('item')
        action = change.get('action')
        details = change.get('details', {})
        backup_path = details.get('backup_path') if isinstance(details, dict) else None

        if not item:
            continue
        if item in restored_files:
            continue

        if action == "created":
            script_content.append(f"log_info 'Removing created file: {item}'")
            script_content.append(f"if [ -e \"{item}\" ]; then")
            script_content.append(f"  run_cmd rm -f \"{item}\"")
            script_content.append(f"else")
            script_content.append(f"  log_warn 'File {item} does not exist, nothing to remove.'")
            script_content.append(f"fi")
            restored_files.add(item)
        elif action == "modified" and backup_path:
            script_content.append(f"log_info 'Restoring backup for: {item}'")
            script_content.append(f"if [ -e \"{backup_path}\" ]; then")
            script_content.append(f"  run_cmd cp -f \"{backup_path}\" \"{item}\"")
            script_content.append(f"  log_info 'Restored {item} from backup {backup_path}'")
            script_content.append(f"else")
            script_content.append(f"  log_warn 'Backup file {backup_path} not found. Cannot restore {item}.'")
            script_content.append(f"fi")
            restored_files.add(item)
        elif action == "modified":
            script_content.append(f"log_info 'No backup available for: {item}'")
            script_content.append(f"log_warn 'Manual restoration may be required for: {item}'")
            restored_files.add(item)

    # --- Kernelstub Parameter Removal ---
    kernelstub_params_to_remove = set()
    if "kernelstub" in changes:
        for change in changes["kernelstub"]:
            if change.get('action') == 'added':
                kernelstub_params_to_remove.add(change.get('item', ''))

    if kernelstub_params_to_remove:
        script_content.append("# --- Removing Kernel Parameters (kernelstub - Pop!_OS) ---")
        script_content.append("if command -v kernelstub >/dev/null 2>&1; then")
        script_content.append("  log_info 'Attempting to remove kernel parameters via kernelstub...'")
        for param in sorted(list(kernelstub_params_to_remove)):
            script_content.append(f"  run_cmd sudo kernelstub --delete-options \"{param}\"")
        script_content.append("else")
        script_content.append("  log_warn ' -> kernelstub command not found. Cannot remove parameters automatically.'")
        script_content.append("fi")
        script_content.append("")

    # --- GRUB Default Reversion Check ---
    # File restore handles /etc/default/grub if backup exists.
    # We just need to trigger update-grub/mkconfig later if it was modified.
    grub_default_file = '/etc/default/grub'
    grub_needs_update = False
    if any(c.get('item') == grub_default_file and c.get('action') == 'modified' and c.get('details', {}).get('backup_path')
           for c in changes.get('files', [])):
        grub_needs_update = True
        script_content.append("# Note: /etc/default/grub restoration handled by file restore section above.")
        script_content.append("# Bootloader update will be triggered later if needed.")

    # --- Update Initramfs ---
    # Should run *after* module configs are reverted
    initramfs_needs_update = False
    if any(c.get('item') == '/etc/modprobe.d/vfio.conf' for c in changes.get('files', [])) or \
       any(c.get('item') == '/etc/modules-load.d/vfio-pci-load.conf' for c in changes.get('files', [])):
        initramfs_needs_update = True

    if initramfs_needs_update:
        script_content.append("# --- Updating Initramfs ---")
        script_content.append("log_info 'Running initramfs update to reflect reverted configurations...'")
        initramfs_update_cmd = ""
        if os.path.exists('/usr/sbin/update-initramfs') or os.path.exists('/sbin/update-initramfs'):
            initramfs_update_cmd = "sudo update-initramfs -u"
        elif os.path.exists('/usr/bin/dracut') or os.path.exists('/sbin/dracut'):
            initramfs_update_cmd = "sudo dracut --force"

        if initramfs_update_cmd:
            script_content.append(f"run_cmd {initramfs_update_cmd}")
        else:
            script_content.append("log_warn 'Could not find update-initramfs or dracut. Manual initramfs update required.'")
        script_content.append("")
    else:
        script_content.append("# Initramfs update deemed unnecessary based on tracked changes.")

    # --- Update Bootloader Config (GRUB) ---
    # Should run after /etc/default/grub is potentially restored and initramfs updated
    if grub_needs_update:
        script_content.append("# --- Updating Bootloader Configuration (GRUB) ---")
        script_content.append("log_info 'Running bootloader update to apply reverted GRUB defaults...'")
        grub_update_cmd = ""
        if os.path.exists('/usr/sbin/update-grub') or os.path.exists('/sbin/update-grub'):
            grub_update_cmd = "sudo update-grub"
        else:
            script_content.append("log_warn 'update-grub not found. Trying alternatives...'")
            
            # Try to find grub.cfg location
            grub_cfg_paths = [
                '/boot/grub/grub.cfg',
                '/boot/grub2/grub.cfg',
                '/boot/efi/EFI/fedora/grub.cfg',
                '/boot/efi/EFI/ubuntu/grub.cfg'
            ]
            
            for cfg_path in grub_cfg_paths:
                script_content.append(f"if [ -e \"{cfg_path}\" ]; then")
                script_content.append(f"  log_info 'Found GRUB config at {cfg_path}'")
                script_content.append(f"  if command -v grub2-mkconfig >/dev/null 2>&1; then")
                script_content.append(f"    run_cmd sudo grub2-mkconfig -o \"{cfg_path}\"")
                script_content.append(f"    break")
                script_content.append(f"  elif command -v grub-mkconfig >/dev/null 2>&1; then")
                script_content.append(f"    run_cmd sudo grub-mkconfig -o \"{cfg_path}\"")
                script_content.append(f"    break")
                script_content.append(f"  fi")
                script_content.append(f"fi")

        if grub_update_cmd:
            script_content.append(f"run_cmd {grub_update_cmd}")
        else:
            script_content.append("log_warn 'Could not determine appropriate GRUB update command.'")
            script_content.append("log_warn 'You may need to manually update your bootloader configuration.'")
        script_content.append("")
    else:
        script_content.append("# GRUB update deemed unnecessary based on tracked changes.")

    # --- BTRFS Snapshot Info ---
    btrfs_snapshots = []
    if "btrfs" in changes:
        for change in changes["btrfs"]:
            if change.get('action') == 'snapshot':
                snap_path = change.get('item')
                if snap_path:
                    btrfs_snapshots.append(snap_path)

    if btrfs_snapshots:
        script_content.append("# --- BTRFS Snapshot Information ---")
        script_content.append("log_info 'BTRFS snapshots were created or identified during setup:'")
        for snap_path in btrfs_snapshots:
            script_content.append(f"log_info ' -> {snap_path}'")
        script_content.append("log_info 'Restoring from snapshots is the most reliable rollback method.'")
        script_content.append("")

    # --- Final Messages ---
    script_content.extend([
        "echo ''",
        "log_info '--- VFIO Setup Cleanup Attempt Finished ---'",
        "log_info 'Review the output above for any errors or warnings.'",
        "log_warn 'A system reboot is recommended to ensure all changes are effective (especially initramfs/kernel params).'",
        "",
        "exit 0"
    ])

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
        os.chmod(script_path_str, 0o755)  # Make executable (rwxr-xr-x)
        log_success(f"Cleanup script created: {script_path_str}")
        log_info("Review the cleanup script carefully before running it with 'sudo bash ...'")
        return script_path_str
    except Exception as e:
        log_error(f"Failed to write cleanup script to {script_path_str}: {e}")
        return None