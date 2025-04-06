"""State tracking for VFIO configuration process."""

import os
import json
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple

from .utils import log_debug, log_info, log_warning


class SystemState:
    """Class for tracking system state and changes during VFIO setup."""
    
    def __init__(self, debug: bool = False, dry_run: bool = False):
        """Initialize the state container.
        
        Args:
            debug: Whether debug mode is enabled
            dry_run: Whether dry run mode is enabled
        """
        self.debug = debug
        self.dry_run = dry_run
        
        # System information
        self.cpu_vendor: str = "unknown"
        self.is_amd_cpu: bool = False
        self.virtualization_enabled: bool = False
        self.secure_boot_status: Optional[bool] = None
        self.bootloader_type: str = "unknown"
        self.iommu_enabled: bool = False
        self.iommu_pt_mode: bool = False
        self.root_is_btrfs: bool = False
        self.libvirt_installed: bool = False
        self.vfio_modules_loaded: bool = False
        
        # GPU information
        self.available_gpus: List[Dict[str, Any]] = []
        self.passthrough_gpu: Optional[Dict[str, Any]] = None
        self.gpu_related_devices: List[Tuple[Dict[str, Any], int]] = []
        self.gpu_iommu_group: Optional[int] = None
        self.device_ids: List[str] = []
        
        # IOMMU groups
        self.iommu_groups: Optional[Dict[int, List[Dict[str, Any]]]] = None
        
        # Configuration changes tracking
        self.changes: Dict[str, Dict[str, Any]] = {}
        
        # Success status
        self.config_status: Dict[str, bool] = {
            "kernel_params": False,
            "vfio_modules": False,
            "initramfs": False,
            "btrfs_snapshot": False
        }

    def track_change(self, change_type: str, details: Dict[str, Any]) -> None:
        """Track a configuration change.
        
        Args:
            change_type: Type of change (e.g., 'bootloader', 'modprobe', etc.)
            details: Dictionary with details about the change
        """
        timestamp = datetime.datetime.now().isoformat()
        if change_type not in self.changes:
            self.changes[change_type] = {
                "timestamp": timestamp,
                "details": details
            }
        else:
            # Update existing change with new details
            self.changes[change_type]["timestamp"] = timestamp
            self.changes[change_type]["details"].update(details)
        
        log_debug(f"Tracked change: {change_type} at {timestamp}", self.debug)
    
    def save_changes(self, output_path: str) -> bool:
        """Save tracked changes to a JSON file.
        
        Args:
            output_path: Path to save the changes JSON
            
        Returns:
            bool: Whether the save was successful
        """
        if not self.changes:
            log_info("No changes to save.")
            return True
            
        if self.dry_run:
            log_debug(f"[DRY RUN] Would save changes to {output_path}", self.debug)
            return True
            
        try:
            # Include system and GPU info in the output
            output_data = {
                "timestamp": datetime.datetime.now().isoformat(),
                "system_info": {
                    "cpu_vendor": self.cpu_vendor,
                    "bootloader": self.bootloader_type,
                    "iommu_enabled": self.iommu_enabled,
                    "secure_boot": self.secure_boot_status,
                },
                "gpu_info": {
                    "passthrough_gpu": self.passthrough_gpu["description"] if self.passthrough_gpu else None,
                    "passthrough_bdf": self.passthrough_gpu["bdf"] if self.passthrough_gpu else None,
                    "device_ids": self.device_ids,
                    "iommu_group": self.gpu_iommu_group
                },
                "changes": self.changes
            }
            
            with open(output_path, 'w') as f:
                json.dump(output_data, f, indent=2)
            
            log_info(f"Saved configuration changes to {output_path}")
            return True
        except Exception as e:
            log_warning(f"Failed to save changes to {output_path}: {e}")
            return False

    def load_changes(self, input_path: str) -> bool:
        """Load previously saved changes from a JSON file.
        
        Args:
            input_path: Path to load the changes JSON from
            
        Returns:
            bool: Whether the load was successful
        """
        if not os.path.exists(input_path):
            log_warning(f"Changes file {input_path} does not exist.")
            return False
            
        try:
            with open(input_path, 'r') as f:
                data = json.load(f)
                
            if "changes" in data:
                self.changes = data["changes"]
                
            if "system_info" in data:
                system_info = data["system_info"]
                self.cpu_vendor = system_info.get("cpu_vendor", self.cpu_vendor)
                self.bootloader_type = system_info.get("bootloader", self.bootloader_type)
                self.iommu_enabled = system_info.get("iommu_enabled", self.iommu_enabled)
                self.secure_boot_status = system_info.get("secure_boot", self.secure_boot_status)
                
            if "gpu_info" in data:
                gpu_info = data["gpu_info"]
                self.device_ids = gpu_info.get("device_ids", self.device_ids)
                self.gpu_iommu_group = gpu_info.get("iommu_group", self.gpu_iommu_group)
                
            log_info(f"Loaded configuration changes from {input_path}")
            return True
        except Exception as e:
            log_warning(f"Failed to load changes from {input_path}: {e}")
            return False
            
    def get_all_backup_files(self) -> List[str]:
        """Get a list of all backup files created during the configuration.
        
        Returns:
            List[str]: List of backup file paths
        """
        backup_files = []
        
        # Look through changes for backup paths
        for change_type, change_info in self.changes.items():
            if "details" in change_info:
                details = change_info["details"]
                # Look for backup_path fields
                if "backup_path" in details and details["backup_path"]:
                    backup_files.append(details["backup_path"])
                    
                # Some changes might track multiple backups in a list
                if "backup_paths" in details and details["backup_paths"]:
                    backup_files.extend([p for p in details["backup_paths"] if p])
        
        return backup_files


def get_state_dir() -> str:
    """Get the directory where state information is stored.
    
    Returns:
        Path to the state directory
    """
    import os
    from pathlib import Path
    
    # Use XDG_DATA_HOME if available, otherwise fallback to ~/.local/share
    xdg_data_home = os.environ.get('XDG_DATA_HOME')
    if xdg_data_home:
        base_dir = Path(xdg_data_home)
    else:
        base_dir = Path.home() / '.local' / 'share'
            
    # Create the state directory if it doesn't exist
    state_dir = base_dir / 'vfio-configurator'
    state_dir.mkdir(parents=True, exist_ok=True)
    
    return str(state_dir)


def get_timestamp() -> str:
    """Get current timestamp in a consistent format.
    
    Returns:
        Timestamp string
    """
    import datetime
    return datetime.datetime.now().strftime("%Y%m%d%H%M%S")


def save_change_record(change_record: dict, debug: bool = False) -> bool:
    """Save a change record to the state file.
    
    Args:
        change_record: Dictionary containing change information
        debug: If True, print additional debug information
    
    Returns:
        True if successfully saved, False otherwise
    """
    import json
    import os
    from vfio_configurator.utils import log_debug, log_error
    
    try:
        state_dir = get_state_dir()
        state_file = os.path.join(state_dir, "changes.json")
        
        # Load existing changes if the file exists
        changes = []
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                changes = json.load(f)
                
        # Add the new change record
        changes.append(change_record)
        
        # Save the updated changes
        with open(state_file, 'w') as f:
            json.dump(changes, f, indent=2)
                
        log_debug(f"Saved change record to {state_file}", debug)
        return True
    except Exception as e:
        log_error(f"Failed to save change record: {str(e)}")
        return False


def track_change(
    changes: Dict[str, List[Dict[str, Any]]], 
    category: str, 
    target: str, 
    action: str, 
    details: Dict[str, Any] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """Track a configuration change in the changes dict.
    
    Args:
        changes: Dictionary tracking changes by category
        category: Category of the change (e.g., 'files', 'modules', 'kernelstub')
        target: Target of the change (e.g., file path, module name)
        action: Action taken (e.g., 'modified', 'added', 'removed')
        details: Any additional details to record about the change
        
    Returns:
        Updated changes dictionary
    """
    if details is None:
        details = {}
        
    # Initialize category if it doesn't exist
    if category not in changes:
        changes[category] = []

    # Create change entry
    change_entry = {
        "target": target,
        "action": action,
        "timestamp": datetime.datetime.now().isoformat()
    }
    
    # Add any additional details
    if details:
        change_entry.update(details)
        
    # Add to the list of changes in this category
    changes[category].append(change_entry)
    
    return changes


def create_cleanup_script(output_dir: str, changes: Dict[str, List[Dict[str, Any]]], dry_run: bool = False, debug: bool = False) -> Optional[str]:
    """Create a cleanup script based on tracked changes.
    
    Args:
        output_dir: Directory to save the cleanup script
        changes: Dictionary with tracked changes
        dry_run: If True, don't actually create the script
        debug: If True, print additional debug information
    
    Returns:
        Path to the created script, or None if creation failed
    """
    from vfio_configurator.utils import log_debug, log_info, log_error, log_success
    
    if dry_run:
        log_debug("[DRY RUN] Would generate cleanup script", debug)
        return None
        
    if not changes:
        log_info("No changes to clean up.")
        return None
    
    try:
        script_path = os.path.join(output_dir, "vfio_cleanup.sh")
        
        with open(script_path, 'w') as f:
            # Script header
            f.write("#!/bin/bash\n")
            f.write("# VFIO Configuration Cleanup Script\n")
            f.write("# Generated on: {}\n\n".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            f.write("set -e\n\n")
            f.write('echo "VFIO Configuration Cleanup Script"\n')
            f.write('echo "This will attempt to revert changes made by the VFIO setup script."\n')
            f.write('echo "--------------------------------------------------------------"\n\n')
            
            # Check for root
            f.write('if [ "$(id -u)" -ne 0 ]; then\n')
            f.write('    echo "This script must be run as root."\n')
            f.write('    exit 1\n')
            f.write('fi\n\n')
            
            # Process different change categories
            for category, category_changes in changes.items():
                if category == "files":
                    f.write('echo "Restoring modified files..."\n')
                    for change in category_changes:
                        if change["action"] == "modified" and "backup_path" in change:
                            target = change["target"]
                            backup = change["backup_path"]
                            f.write('if [ -f "{}" ]; then\n'.format(backup))
                            f.write('    echo "Restoring {}"\n'.format(target))
                            f.write('    cp "{}" "{}" || echo "Failed to restore {}"\n'.format(backup, target, target))
                            f.write('else\n')
                            f.write('    echo "Warning: Backup file {} not found, cannot restore {}"\n'.format(backup, target))
                            f.write('fi\n\n')
                        elif change["action"] == "created":
                            target = change["target"]
                            f.write('if [ -f "{}" ]; then\n'.format(target))
                            f.write('    echo "Removing {}"\n'.format(target))
                            f.write('    rm -f "{}" || echo "Failed to remove {}"\n'.format(target, target))
                            f.write('fi\n\n')
                            
                elif category == "kernelstub":
                    f.write('echo "Reverting kernelstub parameters..."\n')
                    for change in category_changes:
                        if change["action"] == "added":
                            param = change["target"]
                            f.write('echo "Removing kernel parameter: {}"\n'.format(param))
                            f.write('kernelstub --delete-options="{}" || echo "Failed to remove kernel parameter {}"\n'.format(param, param))
                            f.write('\n')
                            
                elif category == "modules":
                    f.write('echo "Restoring module configuration..."\n')
                    # Handle modprobe.d files
                    files_to_remove = set()
                    for change in category_changes:
                        if "file_path" in change:
                            files_to_remove.add(change["file_path"])
                    
                    for file_path in files_to_remove:
                        f.write('if [ -f "{}" ]; then\n'.format(file_path))
                        f.write('    echo "Removing {}"\n'.format(file_path))
                        f.write('    rm -f "{}" || echo "Failed to remove {}"\n'.format(file_path, file_path))
                        f.write('fi\n\n')
            
            # Always update initramfs
            f.write('echo "Updating initramfs to apply changes..."\n')
            f.write('update-initramfs -u || echo "Failed to update initramfs"\n\n')
            
            f.write('echo "Cleanup completed."\n')
            f.write('echo "You should reboot your system for changes to take effect."\n')
        
        # Make the script executable
        os.chmod(script_path, 0o755)
        
        log_success(f"Cleanup script created: {script_path}")
        log_info("You can run this script later to revert changes if needed.")
        
        return script_path
    
    except Exception as e:
        log_error(f"Failed to create cleanup script: {e}")
        return None