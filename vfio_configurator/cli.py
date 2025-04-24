#!/usr/bin/env python3
# filepath: /home/xiao/Documents/source/repo/vfio/vfio_configurator/cli.py
"""Command line interface for VFIO GPU passthrough configuration."""

import os
import sys
import argparse
import shutil
import shlex
import json
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

from vfio_configurator.snapshot import create_btrfs_snapshot_recommendation, check_btrfs
from vfio_configurator.reporting import display_system_summary, verify_after_reboot, display_config_changes_summary
from vfio_configurator.packages import setup_minimal_qemu_environment, is_arch_based

from .utils import (
    Colors, log_info, log_success, log_warning, log_error, log_debug,
    run_command
)
from .checks import (
    check_dependencies, check_root, is_amd_cpu, check_cpu_virtualization,
    check_secure_boot, check_iommu, check_kernel_cmdline_conflicts,
    check_vfio_modules, check_libvirt_installed
)
from .pci import (
    get_gpus, find_gpu_for_passthrough, check_host_gpu_driver,
    get_iommu_groups, find_gpu_related_devices, get_device_ids
)
from .bootloader import (
    detect_bootloader, configure_kernel_parameters
)
from .vfio_mods import configure_vfio_modprobe
from .initramfs import update_initramfs
from .state import track_change, create_cleanup_script


def gather_system_info(debug: bool = False) -> Dict[str, Any]:
    """Gather all relevant system information for VFIO setup."""
    log_info("Gathering system information...")

    system_info: Dict[str, Any] = {
        "root_privileges": os.geteuid() == 0,
        "cpu_vendor_is_amd": is_amd_cpu(),
        "cpu_virtualization": check_cpu_virtualization(debug=debug),
        "secure_boot_enabled": check_secure_boot(debug=debug),  # Store status: True, False, or None
        "kernel_cmdline_conflicts": check_kernel_cmdline_conflicts(debug=debug),
        "btrfs_system": check_btrfs(debug=debug) if 'check_btrfs' in globals() else False,
        "libvirt_installed": check_libvirt_installed(debug=debug),  # Checks common tools & service
        # IOMMU checks
        "iommu_enabled": False,  # Will be set by check_iommu
        "iommu_passthrough_mode": False,  # Will be set by check_iommu
        "iommu_groups": None,  # Will be populated later if IOMMU active
        # VFIO module check
        "vfio_modules_loaded": check_vfio_modules(debug=debug),  # Check current state
        # GPU info - populated below
        "gpus": [],
        "gpu_for_passthrough": None,
        "host_gpu_driver_ok": None,
        "gpu_primary_group_id": None,
        "gpu_related_devices": [],  # List[Tuple[Dict, int]]
        "passthrough_device_ids": [],  # List[str]
    }

    # Check IOMMU status from kernel cmdline
    system_info["iommu_enabled"], system_info["iommu_passthrough_mode"] = check_iommu()

    # Get GPU list (will trigger PCI device fetch with driver check)
    system_info["gpus"] = get_gpus(debug=debug)
    if not system_info["gpus"]:
         log_error("Failed to identify any GPUs. Cannot proceed.")
         # Keep system_info structure consistent, just leave GPU parts empty/None
         return system_info

    # Select GPU for passthrough (interactive if needed)
    system_info["gpu_for_passthrough"] = find_gpu_for_passthrough(system_info["gpus"], debug=debug)
    if not system_info["gpu_for_passthrough"]:
         log_error("No GPU selected or available for passthrough.")
         return system_info  # Cannot proceed without a target GPU

    # Check host GPU driver status using potentially updated driver info
    system_info["host_gpu_driver_ok"] = check_host_gpu_driver(
        system_info["gpus"],
        system_info["gpu_for_passthrough"],
        debug=debug
    )

    # --- IOMMU Group and Device ID Logic ---
    # Only try to get groups and IDs if IOMMU seems enabled from cmdline check
    if system_info["iommu_enabled"]:
        # Get IOMMU groups (will trigger PCI fetch again if not cached, harmless)
        iommu_groups = get_iommu_groups(debug=debug)
        system_info["iommu_groups"] = iommu_groups  # Store raw groups

        if iommu_groups:
            # Find GPU's IOMMU group and all related functions
            primary_group_id, related_devices = find_gpu_related_devices(
                system_info["gpu_for_passthrough"],
                iommu_groups,
                debug=debug
            )
            system_info["gpu_primary_group_id"] = primary_group_id
            system_info["gpu_related_devices"] = related_devices

            # Extract device IDs for VFIO binding from all related devices
            if related_devices:
                system_info["passthrough_device_ids"] = get_device_ids(related_devices)
            else:
                log_warning("No GPU-related devices found in IOMMU groups. Cannot extract passthrough IDs.")
        else:
            log_warning("Failed to get IOMMU groups. Cannot identify devices for passthrough.")
    else:
         log_info("IOMMU not detected as enabled in kernel parameters.")
         log_info("IOMMU group checking and device ID identification will be skipped until IOMMU is enabled and system rebooted.")

    return system_info


def interactive_setup(output_dir: str, system_info: Dict[str, Any], non_interactive: bool = False, dry_run: bool = False, debug: bool = False) -> Tuple[bool, Dict[str, List[Dict[str, Any]]], bool]:
    """Run the setup process interactively based on gathered system info."""
    changes: Dict[str, List[Dict[str, Any]]] = {}
    setup_successful = True
    made_critical_changes = False  # Track if changes requiring reboot were made

    # --- Prerequisite Checks ---
    if not system_info["root_privileges"]:
        log_error("Root privileges required. Aborting.")
        return False, changes, made_critical_changes
        
    if not system_info["cpu_virtualization"]:
        log_error("CPU virtualization (SVM/VT-x) is not enabled. Please enable it in BIOS/UEFI. Aborting.")
        return False, changes, made_critical_changes
        
    if not system_info.get("gpu_for_passthrough"):
        log_error("No GPU selected for passthrough. Aborting.")
        return False, changes, made_critical_changes
        
    if not system_info.get("host_gpu_driver_ok"):
         log_error("Host GPU driver check failed or no suitable host GPU found.")
         if not non_interactive:
             response = input("Continue anyway? (y/n): ").lower()
             if response != 'y':
                 log_info("Setup aborted by user.")
                 return False, changes, made_critical_changes
         else:
             log_warning("Continuing despite host GPU driver issues (non-interactive mode).")

    # --- BTRFS Snapshot ---
    if system_info.get("btrfs_system", False) and 'check_btrfs' in globals() and 'create_btrfs_snapshot_recommendation' in globals():
        print(f"\n{Colors.BOLD}BTRFS Snapshot{Colors.ENDC}")
        snapshot_path = create_btrfs_snapshot_recommendation(dry_run, debug)
        if snapshot_path:
             changes = track_change(changes, "btrfs", snapshot_path, "snapshot")
             log_success(f"BTRFS snapshot created or identified at {snapshot_path}")

    # --- Kernel Parameter Configuration ---
    needs_kernel_param_config = not system_info["iommu_enabled"] or not system_info["iommu_passthrough_mode"]
    kernel_param_result = None
    if needs_kernel_param_config:
        print(f"\n{Colors.BOLD}Kernel Parameter Configuration{Colors.ENDC}")
        response = 'y'  # Default to yes for non-interactive or dry run
        if not non_interactive and not dry_run:
             response = input("Configure kernel parameters for IOMMU and VFIO? (y/n): ").lower()

        if response == 'y':
            kernel_param_result = configure_kernel_parameters(dry_run, debug, output_dir)
            if kernel_param_result and kernel_param_result.get("status"):
                log_success("Kernel parameter configuration completed successfully.")
                made_critical_changes = True
                
                # Track changes for grub/kernelstub/systemd-boot
                method = kernel_param_result.get("method")
                if method == "grub" and kernel_param_result.get("backup_path"):
                    changes = track_change(
                        changes, "files", "/etc/default/grub", "modified",
                        {"backup_path": kernel_param_result.get("backup_path")}
                    )
                elif method == "kernelstub":
                    for param in kernel_param_result.get("added_params", []):
                        changes = track_change(changes, "kernelstub", param, "added")
                elif method == "systemd-boot" and kernel_param_result.get("backup_paths"):
                    # Track all modified systemd-boot entries with specific category
                    for file_path, backup_path in kernel_param_result.get("backup_paths", {}).items():
                        changes = track_change(
                            changes, "systemd-boot", file_path, "modified",
                            {"backup_path": backup_path, "params": kernel_param_result.get("added_params", [])}
                        )
                    # Also add a record of the bootloader type for the cleanup script
                    changes = track_change(
                        changes, "bootloader", "type", "info",
                        {"value": "systemd-boot"}
                    )
            else:
                log_error("Kernel parameter configuration failed.")
                setup_successful = False
        else:
             log_warning("Kernel parameter configuration skipped by user choice.")
             log_warning("IOMMU must be enabled and system rebooted before proceeding with VFIO configuration.")
             setup_successful = False

    # --- VFIO Modprobe/Module Configuration ---
    passthrough_ids = system_info.get("passthrough_device_ids", [])
    # We configure modprobe if we successfully identified IDs AND IOMMU is enabled
    if passthrough_ids and system_info["iommu_enabled"]:
        print(f"\n{Colors.BOLD}VFIO Driver Configuration (modprobe){Colors.ENDC}")
        response = 'y'
        if not non_interactive and not dry_run:
            response = input("Configure VFIO driver options for device passthrough? (y/n): ").lower()

        if response == 'y':
             modprobe_success = configure_vfio_modprobe(passthrough_ids, dry_run, debug)
             if modprobe_success:
                 log_success("VFIO driver configuration completed successfully.")
                 made_critical_changes = True
                 changes = track_change(changes, "files", "/etc/modprobe.d/vfio.conf", "modified")
                 changes = track_change(changes, "files", "/etc/modules-load.d/vfio-pci-load.conf", "modified")
             else:
                 log_error("VFIO driver configuration failed.")
                 setup_successful = False
        else:
             log_warning("VFIO driver configuration skipped by user choice.")

    elif not passthrough_ids and system_info["iommu_enabled"]:
         # IOMMU on, but couldn't get IDs (e.g., group issue, bad ACS)
         log_error("Cannot configure VFIO drivers: Failed to identify device IDs for passthrough.")
         log_warning("This often requires enabling ACS overrides (unsafe) or using a different PCI slot.")
         if not dry_run:
             log_info("You may need to investigate IOMMU grouping issues or ACS override patches.")
    elif not system_info["iommu_enabled"]:
         # IOMMU off, expected not to have IDs yet
         log_info("Skipping VFIO driver configuration (requires IOMMU to be active first).")
         log_info("Run this script again after enabling IOMMU and rebooting.")

    # --- Initramfs Update ---
    # Update if critical changes (kernel params or modprobe) were made
    if made_critical_changes:
        print(f"\n{Colors.BOLD}Initramfs Update{Colors.ENDC}")
        response = 'y'
        if not non_interactive and not dry_run:
             response = input("Update initramfs to include changes? (y/n): ").lower()

        if response == 'y':
            initramfs_success = update_initramfs(dry_run, debug)
            if initramfs_success:
                log_success("Initramfs update completed successfully.")
                changes = track_change(changes, "initramfs", "update", "executed")
            else:
                log_error("Initramfs update failed.")
                log_warning("System may not boot properly with VFIO without a successful initramfs update.")
                setup_successful = False
        else:
             log_warning("Initramfs update skipped by user choice.")
             log_warning("Changes to kernel parameters and VFIO driver config may not take effect correctly.")

    # --- Install Virtualization Software ---
    if not system_info["libvirt_installed"]:
        print(f"\n{Colors.BOLD}Virtualization Software Installation{Colors.ENDC}")
        log_info("Virtualization software (QEMU, Libvirt, etc.) seems missing or incomplete.")
        
        # Check if system is Arch-based
        arch_system = is_arch_based()
        if arch_system:
            response = 'y'
            if not non_interactive and not dry_run:
                response = input("Would you like to install minimal QEMU environment for Arch Linux now? (y/n): ").lower()

            if response == 'y':
                log_info("Installing minimal QEMU environment for VFIO passthrough (Arch Linux)...")
                
                # Run the setup function from the packages module
                setup_result = setup_minimal_qemu_environment(None, dry_run, debug)
                
                if setup_result["status"]:
                    log_success("Minimal QEMU environment installed successfully.")
                    if setup_result["installed_packages"]:
                        log_info(f"Installed packages: {', '.join(setup_result['installed_packages'])}")
                    
                    changes = track_change(changes, "packages", "qemu-minimal", "installed",
                                           {"installed_packages": setup_result["installed_packages"]})
                else:
                    log_error("Failed to install minimal QEMU environment.")
                    if setup_result["failed_packages"]:
                        log_error(f"Failed packages: {', '.join(setup_result['failed_packages'])}")
                    setup_successful = False
            else:
                log_warning("QEMU environment installation skipped by user choice.")
                log_warning("You will need to install virtualization software manually to use the passthrough GPU.")
        else:
            # For non-Arch systems, provide manual instructions
            response = 'y'
            if not non_interactive and not dry_run:
                response = input("Would you like to install virtualization software now? (y/n): ").lower()

            if response == 'y':
                log_info("Please install virtualization software manually using your package manager.")
                log_info("Refer to the distribution-specific suggestions shown earlier.")
                log_info("For Debian/Ubuntu: sudo apt install qemu-kvm libvirt-daemon-system virt-manager")
                log_info("For Fedora: sudo dnf install qemu-kvm libvirt virt-manager")
                log_info("For openSUSE: sudo zypper install qemu-kvm libvirt virt-manager")
            else:
                log_warning("Virtualization software installation skipped by user choice.")
                log_warning("You will need to install this software manually to use the passthrough GPU.")

    # --- Final Outcome ---
    return setup_successful, changes, made_critical_changes


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='VFIO GPU Passthrough Setup Script for AMD GPUs.',
        epilog="Example: sudo python3 -m vfio_configurator --debug",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Simulate all operations without making actual changes. Implies --debug.')
    parser.add_argument('--debug', action='store_true',
                        help='Enable verbose debug output.')
    parser.add_argument('--cleanup', action='store_true',
                        help='Run the generated cleanup script (vfio_cleanup.sh) if it exists in the output directory.')
    parser.add_argument('--output-dir', type=str, default=None,
                        help='Directory to store output files (cleanup script, changes log). Default: directory of the script.')
    parser.add_argument('--non-interactive', action='store_true',
                        help='Attempt non-interactive setup (assume "yes" to prompts). Use with caution.')
    parser.add_argument('--verify', action='store_true',
                        help='Show verification steps to perform after reboot.')
    parser.add_argument('--verify-auto', action='store_true',
                        help='Run automated verification checks with interactive fixing of failed steps.')
    
    args = parser.parse_args()
    
    # Set debug if dry-run is set
    if args.dry_run:
        args.debug = True
        
    return args


def main():
    """Main entry point for the application."""
    args = parse_args()
    
    # Determine output directory
    if args.output_dir:
        output_dir = os.path.abspath(args.output_dir)
    else:
        output_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
    # Validate output directory existence
    output_dir_path = Path(output_dir)
    if not output_dir_path.exists():
        log_info(f"Output directory '{output_dir}' does not exist. Attempting to create.")
        try:
            output_dir_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log_error(f"Failed to create output directory: {e}")
            return 1
    elif not output_dir_path.is_dir():
        log_error(f"Output path '{output_dir}' exists but is not a directory.")
        return 1

    log_info(f"Using output directory: {output_dir}")

    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    mode_str = ""
    if args.cleanup: mode_str += "[CLEANUP MODE] "
    if args.verify or args.verify_auto: mode_str += "[VERIFY MODE] "
    if args.dry_run: mode_str += "[DRY RUN MODE] "
    print(f"{Colors.BOLD}{f'VFIO GPU Passthrough Setup {mode_str}'.strip():^80}{Colors.ENDC}")
    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")

    if args.debug:
        log_debug("Debug mode enabled", True)
    if args.dry_run:
        log_warning("Dry run mode active: No changes will be made to the system.")
    if args.non_interactive:
        log_warning("Non-interactive mode active: Assuming 'yes' to configuration prompts.")

    # --- Dependency Check ---
    if not check_dependencies(debug=args.debug):
        log_error("Missing required system commands. Please install them and retry.")
        return 1

    # --- Root Check ---
    if not check_root():
        return 1
        
    # --- Verification Mode ---
    if args.verify or args.verify_auto:
        if args.verify_auto:
            log_info("Running automated verification checks...")
            verify_after_reboot(args.debug, interactive=True)
        else:
            verify_after_reboot(args.debug, interactive=False)
        return 0
        
    # --- Cleanup Mode ---
    if args.cleanup:
        cleanup_script_path = Path(output_dir) / "vfio_cleanup.sh"
        if not cleanup_script_path.exists():
            log_error(f"Cleanup script not found at: {cleanup_script_path}")
            log_error("Please run the setup script first to generate a cleanup script.")
            return 1

        cleanup_cmd = f"sudo bash {shlex.quote(str(cleanup_script_path))}"
        if args.dry_run:
            log_warning(f"[DRY RUN] Would run cleanup script: {cleanup_cmd}")
            return 0
        else:
            log_info(f"Running cleanup script: {cleanup_cmd}")
            result = run_command(cleanup_cmd, dry_run=False, debug=args.debug)
            if result is not None:
                log_success("Cleanup script completed.")
                return 0
            else:
                log_error("Cleanup script failed or was interrupted.")
                return 1

    # --- Standard Setup Mode ---
    # CPU Check
    if not is_amd_cpu():
        log_warning("This script is tailored for AMD CPUs. Results may vary on other vendors.")
        if not args.non_interactive:
            response = input("Continue anyway? (y/n): ").lower()
            if response != 'y':
                log_info("Setup aborted by user.")
                return 1
        else:
            log_warning("Continuing despite non-AMD CPU (non-interactive mode).")

    # --- Gather System Info ---
    try:
        system_info = gather_system_info(debug=args.debug)
    except Exception as e:
        log_error(f"A critical error occurred during system information gathering: {e}")
        log_error("Cannot continue.")
        if args.debug:
            import traceback
            log_debug(f"Traceback:\n{traceback.format_exc()}", args.debug)
        return 1

    # --- Display Summary ---
    display_system_summary(system_info)

    # --- User Confirmation ---
    if not args.dry_run and not args.non_interactive:
        print()
        proceed = input("Review the summary above. Proceed with configuration changes? (y/n): ").lower()
        if proceed != 'y':
            log_info("Setup aborted by user.")
            return 1
    elif args.dry_run:
        print("\nDry run: Simulating setup process...")
    elif args.non_interactive:
        print("\nNon-interactive mode: Proceeding with setup automatically...")

    # --- Perform Interactive Setup ---
    setup_successful, changes, made_critical_changes = interactive_setup(
        output_dir, system_info, args.non_interactive, args.dry_run, args.debug
    )

    # --- Save Changes Log & Generate Cleanup Script ---
    cleanup_script_path_str = None
    if changes:
        changes_file_path = Path(output_dir) / "vfio_changes.json"
        try:
            with open(changes_file_path, 'w') as f:
                json.dump(changes, f, indent=2, default=str)
            log_success(f"Changes log saved to {changes_file_path}")
            
            # Generate cleanup script
            cleanup_script_path_str = create_cleanup_script(output_dir, changes, args.dry_run, args.debug)
        except Exception as e:
            log_error(f"Failed to save changes log or generate cleanup script: {e}")

    # --- Final Messages ---
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    if setup_successful:
        if args.dry_run:
            log_success("[DRY RUN] VFIO setup simulation completed. No actual changes were made.")
            log_success("Run the script without --dry-run to apply the changes.")
        else:
            log_success("VFIO setup completed successfully!")
            if made_critical_changes:
                log_warning("A system REBOOT is required for changes to take effect.")
                log_info("After rebooting, run with --verify to see verification steps.")
                log_info("Or use --verify-auto for interactive verification with automatic fix options.")

        return 0  # Success
    else:
        log_error("VFIO setup process failed or was aborted.")
        log_info("Review the errors above. Some changes might have been partially applied.")
        if cleanup_script_path_str and Path(cleanup_script_path_str).exists():
            log_info(f"You can run the cleanup script to revert changes: sudo bash {cleanup_script_path_str}")
            log_info("Or run this script with --cleanup to execute the cleanup script.")
        elif changes:
            log_info("Changes were tracked but cleanup script generation failed.")
        return 1  # Failure


if __name__ == "__main__":
    sys.exit(main())