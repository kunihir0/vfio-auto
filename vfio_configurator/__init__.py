"""VFIO Configurator package for GPU passthrough setup."""

# Export public modules and functions
from .cli import main, gather_system_info, display_system_summary, interactive_setup, verify_after_reboot
from .snapshot import check_btrfs, create_btrfs_snapshot_recommendation
from .utils import Colors, log_info, log_success, log_warning, log_error, log_debug, run_command

__all__ = [
    # Main CLI functions
    'main', 'gather_system_info', 'display_system_summary', 'interactive_setup', 'verify_after_reboot',
    # Snapshot functions
    'check_btrfs', 'create_btrfs_snapshot_recommendation',
    # Utility functions
    'Colors', 'log_info', 'log_success', 'log_warning', 'log_error', 'log_debug', 'run_command'
]
