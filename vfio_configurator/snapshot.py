#!/usr/bin/env python3
# filepath: /home/xiao/Documents/source/repo/vfio/vfio_configurator/snapshot.py
"""BTRFS snapshot functionality for VFIO configuration."""

import datetime
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from .utils import log_info, log_success, log_warning, log_error, log_debug, run_command


def check_btrfs(debug: bool = False) -> bool:
    """Check if the root filesystem is BTRFS."""
    log_info("Checking root filesystem type...")
    # Use findmnt for reliability
    root_fs_type = run_command("findmnt -n -o FSTYPE --target /", debug=debug, dry_run=False)  # Read-only command

    if root_fs_type and root_fs_type.lower() == "btrfs":
        log_success("BTRFS filesystem detected on root '/'.")
        return True
    else:
        log_info(f"Root filesystem is not BTRFS (detected: {root_fs_type or 'Unknown'}).")
        return False


def find_existing_vfio_snapshots(snapshot_base_dir: Path, prefix: str = "pre_vfio_setup_", debug: bool = False) -> List[Tuple[Path, float]]:
    """Find existing BTRFS snapshots created by this script."""
    existing_snapshots: List[Tuple[Path, float]] = []
    if not snapshot_base_dir.is_dir():
        log_debug(f"Snapshot base directory {snapshot_base_dir} does not exist.", debug)
        return []

    try:
        for item in snapshot_base_dir.iterdir():
            # Check if it's a directory (subvolume/snapshot) and matches prefix
            if item.is_dir() and item.name.startswith(prefix):
                try:
                    creation_time = item.stat().st_ctime
                    existing_snapshots.append((item, creation_time))
                except (OSError, FileNotFoundError) as e:
                    log_debug(f"Error getting stats for {item}: {e}", debug)
    except (PermissionError, OSError) as e:
        log_error(f"Error scanning for existing snapshots in {snapshot_base_dir}: {e}")

    # Sort by creation time, newest first
    existing_snapshots.sort(key=lambda x: x[1], reverse=True)
    log_debug(f"Found {len(existing_snapshots)} existing snapshots with prefix '{prefix}'.", debug)
    return existing_snapshots


def create_btrfs_snapshot_recommendation(dry_run: bool = False, debug: bool = False) -> Optional[str]:
    """Handle BTRFS snapshot creation, checking for existing ones."""
    snapshot_base_dir = Path("/.snapshots")  # Common location
    # Try alternative if /.snapshots doesn't exist but /btrfs_pool/.snapshots does?
    if not snapshot_base_dir.exists():
        # Maybe check /mnt, /run/timeshift? Very heuristic. Stick to /.snapshots for now.
        log_info(f"Default BTRFS snapshot directory {snapshot_base_dir} not found.")
        # Ask user for path?
        user_path = input(f"Enter path for BTRFS snapshots or leave blank to skip: ").strip()
        if not user_path:
            log_info("Skipping BTRFS snapshot recommendation.")
            return None
        snapshot_base_dir = Path(user_path)
        if not snapshot_base_dir.is_dir():
            log_warning(f"Provided path '{snapshot_base_dir}' is not a directory. Skipping snapshot.")
            return None

    snapshot_prefix = "vfio_setup_backup_"  # Prefix for our snapshots

    # Check for existing snapshots first
    existing = find_existing_vfio_snapshots(snapshot_base_dir, snapshot_prefix, debug)

    use_existing = False
    if existing:
        most_recent_path, most_recent_time = existing[0]
        creation_time_str = datetime.datetime.fromtimestamp(most_recent_time).strftime('%Y-%m-%d %H:%M:%S')
        log_info(f"Found potentially relevant existing snapshot: {most_recent_path} (created {creation_time_str})")
        if not dry_run:  # Don't ask in dry run
            response = input("Use this existing snapshot instead of creating a new one? (y/n): ").lower()
            if response == 'y':
                log_info(f"Using existing snapshot: {most_recent_path}")
                use_existing = True
            else:
                log_info("Will create a new snapshot.")
                use_existing = False
        else:
            log_debug(f"[DRY RUN] Would have offered to use existing snapshot: {most_recent_path}", debug)
            # Simulate choosing to create a new one for dry run consistency
            use_existing = False

    if use_existing:
        return str(most_recent_path)  # Return existing path

    # Create a new snapshot
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_name = f"{snapshot_prefix}{timestamp}"
    snapshot_path = snapshot_base_dir / snapshot_name
    snapshot_path_str = str(snapshot_path)

    # Check if snapshot tool exists
    btrfs_cmd = shutil.which("btrfs")
    if not btrfs_cmd:
        log_warning("'btrfs' command not found. Cannot create snapshot.")
        return None

    # Check if root is actually on a btrfs subvolume mounted at /
    # This is tricky. `findmnt -n -o SOURCE --target /` might give /dev/sdaX, not subvol info.
    # `btrfs subvolume get-default /` might work.
    is_root_subvol = False
    try:
        get_default_cmd = f"sudo {btrfs_cmd} subvolume get-default /"
        result = run_command(get_default_cmd, dry_run=False, debug=debug)  # Read-only check
        if result and 'ID' in result:  # Simple check if command succeeded
            is_root_subvol = True
            log_debug("Root appears to be a BTRFS subvolume.", debug)
        else:
            log_warning("Could not confirm '/' is the top-level BTRFS subvolume. Snapshot command might need adjustment.")
    except Exception as e:
        log_warning(f"Error checking root subvolume status: {e}")

    # Use subvolume snapshot command
    # Needs sudo
    create_command = f"sudo {btrfs_cmd} subvolume snapshot / {snapshot_path_str}"

    log_info("System uses BTRFS. It's recommended to create a snapshot before proceeding.")
    log_info(f"Proposed command: {create_command}")
    log_info("This allows reverting changes if needed (e.g., using Timeshift/Snapper or manually).")
    log_info("Manual restore example (USE WITH EXTREME CAUTION - DESTROYS CURRENT ROOT):")
    log_info(f"  1. Boot from live USB")
    log_info(f"  2. Mount BTRFS top-level volume (e.g., mount /dev/sdxY /mnt)")
    log_info(f"  3. cd /mnt")
    log_info(f"  4. mv @ /@_bad # Rename current root subvolume (often named @)")
    log_info(f"  5. btrfs subvolume snapshot .snapshots/{snapshot_name} @ # Restore snapshot as new root")
    log_info(f"  6. sync; reboot")

    if not dry_run:
        response = input("Create this BTRFS snapshot now? (y/n): ").lower()
        if response != 'y':
            log_info("Skipping snapshot creation.")
            return None  # User skipped

    # Ensure /.snapshots directory exists (or chosen base dir)
    if dry_run:
        log_debug(f"[DRY RUN] Would ensure directory exists: {snapshot_base_dir}", debug)
        log_debug(f"[DRY RUN] Would run command: {create_command}", debug)
        log_success(f"[DRY RUN] BTRFS snapshot would be created at {snapshot_path_str}")
        return snapshot_path_str  # Return the intended path
    else:
        try:
            # Check permissions and existence of base dir
            if not snapshot_base_dir.exists():
                log_info(f"Creating snapshot directory: {snapshot_base_dir}")
                run_command(f"sudo mkdir -p {snapshot_base_dir}", dry_run=False, debug=debug)

            # Create the actual snapshot
            result = run_command(create_command, dry_run=False, debug=debug)
            if result is not None:
                log_success(f"BTRFS snapshot created at {snapshot_path_str}")
                return snapshot_path_str
            else:
                log_error("Failed to create BTRFS snapshot.")
                return None

        except Exception as e:
            log_error(f"Error creating BTRFS snapshot: {e}")
            return None