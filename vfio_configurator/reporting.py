#!/usr/bin/env python3
# filepath: /home/xiao/Documents/source/repo/vfio/vfio_configurator/reporting.py
"""Reporting functionality for VFIO configuration."""

from typing import Dict, Any, Optional, List

from .utils import Colors, log_info, log_success, log_warning, log_error


def display_system_summary(system_info: Dict[str, Any]) -> None:
    """Display a formatted summary of the gathered system information."""
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    print(f"{Colors.BOLD}{'VFIO Setup - System Summary':^80}{Colors.ENDC}")
    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")

    # --- Prerequisites ---
    print(f"{Colors.BOLD}Prerequisites:{Colors.ENDC}")
    def print_status(label: str, status: Optional[bool], ok_msg: str = "", warn_msg: str = "", err_msg: str = "", info_msg: str = ""):
        if status is True:
            print(f"  {Colors.GREEN}✓{Colors.ENDC} {label}: {ok_msg}")
        elif status is False:
            print(f"  {Colors.RED}✗{Colors.ENDC} {label}: {err_msg}")
        elif status is None:
            print(f"  {Colors.YELLOW}?{Colors.ENDC} {label}: {warn_msg}")
        else:
            print(f"  {Colors.BLUE}i{Colors.ENDC} {label}: {info_msg}")

    # Root privileges
    print_status(
        "Root privileges", 
        system_info["root_privileges"], 
        ok_msg="Running as root", 
        err_msg="Not running as root (required)"
    )
    
    # CPU Virtualization
    print_status(
        "CPU Virtualization (SVM/VT-x)", 
        system_info["cpu_virtualization"], 
        ok_msg="Enabled", 
        err_msg="Not enabled in /proc/cpuinfo (check BIOS/output)"
    )
    
    # IOMMU Enabled
    print_status(
        "IOMMU Enabled (Kernel Param)", 
        system_info["iommu_enabled"], 
        ok_msg="Found amd/intel_iommu=on", 
        warn_msg="Not found (will attempt to configure)", 
        err_msg="Not found (will attempt to configure)"
    )
    
    # IOMMU Passthrough
    print_status(
        "IOMMU Passthrough Mode (iommu=pt)", 
        system_info["iommu_passthrough_mode"], 
        ok_msg="Found iommu=pt", 
        warn_msg="Not found (recommended, will attempt to configure)", 
        err_msg="Not found (recommended, will attempt to configure)"
    )

    # Secure Boot Status
    sb_status = system_info.get('secure_boot_enabled')
    import shutil
    sb_msg = "Disabled" if sb_status is False else ("ENABLED (Potential issue for module loading)" if sb_status is True else "Could not determine")
    sb_label = f"Secure Boot Status ({'mokutil' if shutil.which('mokutil') else 'EFI Var'})"
    print_status(
        sb_label, 
        sb_status is False, 
        ok_msg=sb_msg, 
        warn_msg=sb_msg, 
        err_msg=sb_msg
    )

    # --- GPU Information ---
    print(f"\n{Colors.BOLD}GPU Setup:{Colors.ENDC}")
    passthrough_gpu = system_info.get("gpu_for_passthrough")
    if passthrough_gpu:
        gpu_desc = passthrough_gpu.get('description', 'Unknown GPU')
        gpu_bdf = passthrough_gpu.get('bdf', '??:??.?')
        gpu_ids = f"{passthrough_gpu.get('vendor_id', '????')}:{passthrough_gpu.get('device_id', '????')}"
        print_status(
            "GPU for Passthrough Selected", 
            True, 
            ok_msg=f"{gpu_desc} [{gpu_ids}] at {gpu_bdf}"
        )

        host_driver_ok = system_info.get("host_gpu_driver_ok")
        host_driver_msg = "Host GPU seems to have a driver" if host_driver_ok else "Host GPU driver issue detected / No other GPU"
        print_status(
            "Host GPU Status", 
            host_driver_ok, 
            ok_msg=host_driver_msg, 
            err_msg=host_driver_msg
        )

        primary_group_id = system_info.get("gpu_primary_group_id")
        related_devs = system_info.get("gpu_related_devices", [])

        if system_info["iommu_enabled"]:
            if primary_group_id is not None:
                print_status(
                    f"IOMMU Group", 
                    True, 
                    ok_msg=f"GPU in IOMMU Group {primary_group_id} with {len(related_devs)} related device(s)"
                )
            else:
                print_status(
                    f"IOMMU Group", 
                    False, 
                    err_msg="Could not identify GPU's IOMMU group"
                )
        else:
            print_status(
                f"IOMMU Group", 
                None, 
                warn_msg="IOMMU not enabled, cannot identify groups"
            )

        passthrough_ids = system_info.get("passthrough_device_ids", [])
        if passthrough_ids:
            print_status(
                f"Device IDs", 
                True, 
                ok_msg=f"Found {len(passthrough_ids)} unique device IDs to pass through"
            )
        elif system_info["iommu_enabled"] and primary_group_id is not None:
            print_status(
                f"Device IDs", 
                False, 
                err_msg="Failed to identify device IDs for passthrough despite finding IOMMU group"
            )
        else:
            print_status(
                f"Device IDs", 
                None, 
                warn_msg="Cannot identify IDs until IOMMU is enabled and system rebooted"
            )

    else:
        print_status(
            "GPU for Passthrough Selected", 
            False, 
            err_msg="No suitable AMD GPU found or selected."
        )

    # --- Other Checks ---
    print(f"\n{Colors.BOLD}System Configuration:{Colors.ENDC}")
    print_status(
        "VFIO Modules Loaded", 
        system_info["vfio_modules_loaded"], 
        ok_msg="Modules (vfio, vfio_pci, etc.) are currently loaded", 
        warn_msg="Not all modules loaded (Expected before reboot/config)"
    )
    
    print_status(
        "Kernel Cmdline vfio-pci.ids", 
        not system_info["kernel_cmdline_conflicts"], 
        ok_msg="No conflicting 'vfio-pci.ids' found", 
        err_msg="Found 'vfio-pci.ids' (Potential conflict with modprobe)"
    )
    
    print_status(
        "BTRFS Root Filesystem", 
        system_info["btrfs_system"], 
        ok_msg="Detected (Snapshot recommended)", 
        info_msg="Not detected"
    )
    
    print_status(
        "Virtualization Host Software", 
        system_info["libvirt_installed"], 
        ok_msg="Tools like virsh/qemu/libvirtd found", 
        warn_msg="Some tools seem missing (Installation recommended)"
    )

    # --- Proposed Actions ---
    print(f"\n{Colors.BOLD}Configuration Actions Needed:{Colors.ENDC}")
    action_needed = False
    
    if not system_info["iommu_enabled"] or not system_info["iommu_passthrough_mode"]:
        print(f"  {Colors.YELLOW}→{Colors.ENDC} Configure kernel parameters for IOMMU (via Grub or kernelstub).")
        action_needed = True
    else:
        print(f"  {Colors.GREEN}✓{Colors.ENDC} Kernel parameters for IOMMU appear correctly set.")

    if system_info.get("passthrough_device_ids"):  # If we have IDs, we need to configure modprobe
        print(f"  {Colors.YELLOW}→{Colors.ENDC} Configure VFIO driver options (modprobe.d) for passthrough devices.")
        action_needed = True
    else:
        if system_info["iommu_enabled"] and system_info.get("gpu_primary_group_id") is not None:
            print(f"  {Colors.RED}✗{Colors.ENDC} Failed to identify device IDs despite finding IOMMU group.")
        elif not system_info["iommu_enabled"]:
            print(f"  {Colors.BLUE}i{Colors.ENDC} VFIO driver configuration pending (requires IOMMU and reboot first).")
        else:
            print(f"  {Colors.BLUE}i{Colors.ENDC} VFIO driver configuration status unclear.")

    # Initramfs update needed if kernel params or modules are configured
    if (not system_info["iommu_enabled"] or not system_info["iommu_passthrough_mode"]) or system_info.get("passthrough_device_ids"):
        print(f"  {Colors.YELLOW}→{Colors.ENDC} Update initramfs to include changes.")
        action_needed = True
    else:
        print(f"  {Colors.GREEN}✓{Colors.ENDC} Initramfs update likely not needed based on current checks.")

    if not system_info["libvirt_installed"]:
        print(f"  {Colors.YELLOW}→{Colors.ENDC} Install virtualization software (QEMU, Libvirt) - Recommended.")

    if system_info["btrfs_system"]:
        print(f"  {Colors.BLUE}i{Colors.ENDC} Create a BTRFS snapshot before proceeding (Recommended).")

    if not action_needed and system_info["iommu_enabled"] and system_info.get("passthrough_device_ids"):
        print(f"  {Colors.GREEN}✓{Colors.ENDC} System appears mostly configured for VFIO setup steps handled by this script.")
        print(f"  {Colors.BLUE}i{Colors.ENDC} Ensure initramfs was updated after last relevant change.")

    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")


def verify_after_reboot(debug: bool = False) -> None:
    """Run checks that are only meaningful after a reboot."""
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    print(f"{Colors.BOLD}{'Post-Reboot Verification Steps':^80}{Colors.ENDC}")
    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    log_info("After rebooting, please perform these checks manually:")

    # 1. Check Kernel Parameters
    print(f"\n{Colors.BOLD}1. Verify Kernel Parameters:{Colors.ENDC}")
    log_info("  Run: cat /proc/cmdline")
    log_info("  Ensure 'amd_iommu=on' (or 'intel_iommu=on'), 'iommu=pt', and 'rd.driver.pre=vfio-pci' are present.")

    # 2. Check IOMMU activation in dmesg
    print(f"\n{Colors.BOLD}2. Verify IOMMU is Active (dmesg):{Colors.ENDC}")
    log_info("  Run: sudo dmesg | grep -i -e DMAR -e IOMMU")
    log_info("  Look for messages indicating IOMMU initialization (e.g., 'AMD-Vi: IOMMU performance counters supported', 'DMAR: IOMMU enabled', 'Added domain '). Errors like 'Failed to enable IOMMU' indicate problems.")

    # 3. Check IOMMU groups again
    print(f"\n{Colors.BOLD}3. Verify IOMMU Groups:{Colors.ENDC}")
    log_info("  Run: for d in /sys/kernel/iommu_groups/*/devices/*; do n=${d#*/iommu_groups/*}; n=${n%%/*}; printf 'IOMMU Group %s ' \"$n\"; lspci -nns \"${d##*/}\"; done | sort -n -k3")
    log_info("  Verify your passthrough GPU and its components (e.g., .0 and .1 functions) are listed.")
    log_info("  Check if they are in well-isolated groups (ideally separate groups, or a group containing only the GPU functions). Poor isolation might require ACS override patches (use with caution).")

    # 4. Check VFIO driver binding
    print(f"\n{Colors.BOLD}4. Verify GPU Driver Binding:{Colors.ENDC}")
    log_info("  Run: lspci -nnk")
    log_info("  Find your passthrough AMD GPU and its related functions (e.g., Audio device).")
    log_info("  Check the 'Kernel driver in use:' line. It SHOULD show 'vfio-pci'.")
    log_info("  Example for GPU:")
    log_info("    0b:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. [AMD/ATI] Navi 21 [1002:73bf] (rev c1)")
    log_info("            Subsystem: ...")
    log_info("            Kernel driver in use: vfio-pci")  # <--- THIS IS KEY
    log_info("            Kernel modules: amdgpu")
    log_info("  Example for Audio:")
    log_info("    0b:00.1 Audio device [0403]: Advanced Micro Devices, Inc. [AMD/ATI] Navi 21 HDMI Audio [1002:ab28]")
    log_info("            Subsystem: ...")
    log_info("            Kernel driver in use: vfio-pci")  # <--- THIS IS KEY
    log_info("            Kernel modules: snd_hda_intel")

    # 5. Check Host GPU
    print(f"\n{Colors.BOLD}5. Verify Host GPU:{Colors.ENDC}")
    log_info("  Ensure your host display is working correctly.")
    log_info("  Run: lspci -nnk | grep -A3 VGA")
    log_info("  Check if your host GPU has an appropriate driver loaded (e.g., 'nvidia', 'nouveau', 'amdgpu', 'i915')")

    # Next Steps
    print(f"\n{Colors.BOLD}Next Steps (If Verification Passes):{Colors.ENDC}")
    log_info("1. Install Virtual Machine Manager: `virt-manager` is recommended if not installed.")
    log_info("2. Create a New VM: Use virt-manager or `virsh`.")
    log_info("3. Customize VM Configuration *before* installing OS:")
    log_info("   - Enable XML editing in virt-manager (Edit -> Preferences -> Enable XML editing).")
    log_info("   - Set Firmware to UEFI x86_64 (OVMF). Ensure `ovmf` package is installed.")
    log_info("   - Chipset: Q35 is generally recommended over i440FX.")
    log_info("4. Add Passthrough Devices:")
    log_info("   - Go to 'Add Hardware' -> 'PCI Host Device'.")
    log_info("   - Add the passthrough GPU function (e.g., 0b:00.0).")
    log_info("   - Add the passthrough GPU's Audio function (e.g., 0b:00.1).")

    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.ENDC}")


def display_config_changes_summary(changes: Dict[str, List[Dict[str, Any]]]) -> None:
    """Display a summary of configuration changes made by the script."""
    if not changes:
        log_info("No configuration changes were made.")
        return

    print(f"\n{Colors.BOLD}Configuration Changes Summary:{Colors.ENDC}")
    
    # Files modified
    file_changes = changes.get("files", [])
    if file_changes:
        print(f"  {Colors.BLUE}Files modified ({len(file_changes)}):{Colors.ENDC}")
        for change in file_changes:
            action = change.get("action", "unknown")
            item = change.get("item", "unknown file")
            if action == "created":
                print(f"    - Created: {item}")
            elif action == "modified":
                print(f"    - Modified: {item}")
            else:
                print(f"    - {action.capitalize()}: {item}")
    
    # Kernel parameters
    kernel_changes = changes.get("kernelstub", [])
    if kernel_changes:
        print(f"  {Colors.BLUE}Kernel parameters added ({len(kernel_changes)}):{Colors.ENDC}")
        for change in kernel_changes:
            item = change.get("item", "unknown param")
            print(f"    - {item}")
    
    # BTRFS snapshots
    btrfs_changes = changes.get("btrfs", [])
    if btrfs_changes:
        print(f"  {Colors.BLUE}BTRFS snapshots ({len(btrfs_changes)}):{Colors.ENDC}")
        for change in btrfs_changes:
            item = change.get("item", "unknown snapshot")
            print(f"    - {item}")
    
    # Initramfs updates
    initramfs_changes = changes.get("initramfs", [])
    if initramfs_changes:
        print(f"  {Colors.BLUE}Initramfs updates ({len(initramfs_changes)}):{Colors.ENDC}")
        for change in initramfs_changes:
            item = change.get("item", "update")
            print(f"    - {item}")

    # Other categories
    for category, category_changes in changes.items():
        if category not in ["files", "kernelstub", "btrfs", "initramfs"] and category_changes:
            print(f"  {Colors.BLUE}{category.capitalize()} ({len(category_changes)}):{Colors.ENDC}")
            for change in category_changes:
                item = change.get("item", "unknown")
                action = change.get("action", "unknown")
                print(f"    - {action.capitalize()}: {item}")