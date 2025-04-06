#!/usr/bin/env python3
# filepath: /home/xiao/Documents/source/repo/vfio/vfio_configurator/reporting.py
"""Reporting functionality for VFIO configuration."""

import os
import sys
import re
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Union, Callable

from .utils import Colors, log_info, log_success, log_warning, log_error, log_debug, run_command
from .state import track_change
from .bootloader import configure_kernel_parameters
from .vfio_mods import configure_vfio_modprobe
from .initramfs import update_initramfs


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


def verify_after_reboot(debug: bool = False, interactive: bool = False) -> bool:
    """Run checks that are only meaningful after a reboot.
    
    Args:
        debug: Enable debug output
        interactive: Enable interactive verification with automated checks
        
    Returns:
        bool: True if all verification steps passed or were fixed, False otherwise
    """
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    print(f"{Colors.BOLD}{'Post-Reboot Verification Steps':^80}{Colors.ENDC}")
    print(f"{Colors.BOLD}{'=' * 80}{Colors.ENDC}")
    
    if not interactive:
        log_info("After rebooting, please perform these checks manually:")
        _show_manual_verification_steps()
        return False  # No automated verification was performed
    
    log_info("Running automated verification checks...")
    
    # Track the verification status
    verification_results = {}
    verification_success = True
    
    # Run each verification step
    verification_steps = [
        ("kernel_parameters", "Kernel Parameters", _verify_kernel_parameters),
        ("iommu_active", "IOMMU Activation", _verify_iommu_active),
        ("iommu_groups", "IOMMU Groups", _verify_iommu_groups),
        ("vfio_binding", "VFIO Driver Binding", _verify_vfio_binding),
        ("host_gpu", "Host GPU", _verify_host_gpu)
    ]
    
    for step_id, step_name, verify_func in verification_steps:
        print(f"\n{Colors.BOLD}{step_name} Verification:{Colors.ENDC}")
        success, result = verify_func(debug)
        verification_results[step_id] = {
            "success": success,
            "result": result
        }
        
        if not success:
            verification_success = False
            
            # If a step fails, offer to fix it
            if _ask_to_fix_issue(step_name):
                fix_success = _attempt_to_fix_issue(step_id, result, debug)
                if fix_success:
                    log_success(f"Successfully fixed {step_name} issue!")
                    verification_results[step_id]["fixed"] = True
                else:
                    log_error(f"Could not automatically fix {step_name} issue.")
                    verification_results[step_id]["fixed"] = False
    
    # Summary of results
    print(f"\n{Colors.BOLD}Verification Results Summary:{Colors.ENDC}")
    for step_id, step_name, _ in verification_steps:
        result = verification_results[step_id]
        if result["success"]:
            print(f"  {Colors.GREEN}✓{Colors.ENDC} {step_name}: Passed")
        elif result.get("fixed", False):
            print(f"  {Colors.YELLOW}→{Colors.ENDC} {step_name}: Fixed (was failing)")
        else:
            print(f"  {Colors.RED}✗{Colors.ENDC} {step_name}: Failed")
    
    # Final result
    if verification_success:
        log_success("All verification steps passed! Your system is ready for VFIO GPU passthrough.")
        _show_next_steps()
        return True
    else:
        fixed_count = sum(1 for step_id in verification_results if verification_results[step_id].get("fixed", False))
        if fixed_count > 0:
            log_warning(f"Some verification steps were fixed ({fixed_count}), but some still have issues.")
        else:
            log_error("Verification failed. Please review the issues above and fix them manually.")
        
        # Show manual steps for failed verifications
        print(f"\n{Colors.BOLD}Manual Steps for Failed Verifications:{Colors.ENDC}")
        _show_manual_verification_steps(only_ids=[
            step_id for step_id, data in verification_results.items() 
            if not data["success"] and not data.get("fixed", False)
        ])
        
        return False


def _ask_to_fix_issue(step_name: str) -> bool:
    """Ask the user if they want to attempt to fix a failed verification step."""
    response = input(f"{Colors.YELLOW}Would you like to attempt to fix the {step_name} issue? (y/n): {Colors.ENDC}").lower()
    return response == 'y'


def _attempt_to_fix_issue(step_id: str, result: Dict[str, Any], debug: bool = False) -> bool:
    """Attempt to fix a failed verification step.
    
    Args:
        step_id: The identifier of the verification step
        result: The result data from the verification step
        debug: Enable debug output
        
    Returns:
        bool: True if the fix was successful, False otherwise
    """
    # Map step IDs to their fix functions
    fix_functions = {
        "kernel_parameters": _fix_kernel_parameters,
        "iommu_active": _fix_iommu_active,
        "iommu_groups": _fix_iommu_groups,
        "vfio_binding": _fix_vfio_binding,
        "host_gpu": _fix_host_gpu
    }
    
    if step_id in fix_functions:
        return fix_functions[step_id](result, debug)
    
    log_error(f"No automatic fix available for {step_id}")
    return False


def _show_manual_verification_steps(only_ids: List[str] = None) -> None:
    """Show manual verification steps.
    
    Args:
        only_ids: If provided, only show steps for these IDs
    """
    # Map of step IDs to their descriptions and commands
    manual_steps = {
        "kernel_parameters": {
            "title": "1. Verify Kernel Parameters:",
            "steps": [
                "  Run: cat /proc/cmdline",
                "  Ensure 'amd_iommu=on' (or 'intel_iommu=on'), 'iommu=pt', and 'rd.driver.pre=vfio-pci' are present."
            ]
        },
        "iommu_active": {
            "title": "2. Verify IOMMU is Active (dmesg):",
            "steps": [
                "  Run: sudo dmesg | grep -i -e DMAR -e IOMMU",
                "  Look for messages indicating IOMMU initialization (e.g., 'AMD-Vi: IOMMU performance counters supported', 'DMAR: IOMMU enabled', 'Added domain '). Errors like 'Failed to enable IOMMU' indicate problems."
            ]
        },
        "iommu_groups": {
            "title": "3. Verify IOMMU Groups:",
            "steps": [
                "  Run: for d in /sys/kernel/iommu_groups/*/devices/*; do n=${d#*/iommu_groups/*}; n=${n%%/*}; printf 'IOMMU Group %s ' \"$n\"; lspci -nns \"${d##*/}\"; done | sort -n -k3",
                "  Verify your passthrough GPU and its components (e.g., .0 and .1 functions) are listed.",
                "  Check if they are in well-isolated groups (ideally separate groups, or a group containing only the GPU functions). Poor isolation might require ACS override patches (use with caution)."
            ]
        },
        "vfio_binding": {
            "title": "4. Verify GPU Driver Binding:",
            "steps": [
                "  Run: lspci -nnk",
                "  Find your passthrough AMD GPU and its related functions (e.g., Audio device).",
                "  Check the 'Kernel driver in use:' line. It SHOULD show 'vfio-pci'.",
                "  Example for GPU:",
                "    0b:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. [AMD/ATI] Navi 21 [1002:73bf] (rev c1)",
                "            Subsystem: ...",
                "            Kernel driver in use: vfio-pci",  # <--- THIS IS KEY
                "            Kernel modules: amdgpu",
                "  Example for Audio:",
                "    0b:00.1 Audio device [0403]: Advanced Micro Devices, Inc. [AMD/ATI] Navi 21 HDMI Audio [1002:ab28]",
                "            Subsystem: ...",
                "            Kernel driver in use: vfio-pci",  # <--- THIS IS KEY
                "            Kernel modules: snd_hda_intel"
            ]
        },
        "host_gpu": {
            "title": "5. Verify Host GPU:",
            "steps": [
                "  Ensure your host display is working correctly.",
                "  Run: lspci -nnk | grep -A3 VGA",
                "  Check if your host GPU has an appropriate driver loaded (e.g., 'nvidia', 'nouveau', 'amdgpu', 'i915')"
            ]
        }
    }
    
    # Show all steps or just the ones specified
    for step_id, step_data in manual_steps.items():
        if only_ids is None or step_id in only_ids:
            print(f"\n{Colors.BOLD}{step_data['title']}{Colors.ENDC}")
            for step in step_data["steps"]:
                log_info(step)


def _show_next_steps() -> None:
    """Show next steps after successful verification."""
    print(f"\n{Colors.BOLD}Next Steps:{Colors.ENDC}")
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


#
# Individual verification functions
#

def _verify_kernel_parameters(debug: bool = False) -> Tuple[bool, Dict[str, Any]]:
    """Verify kernel parameters for VFIO.
    
    Args:
        debug: Enable debug output
        
    Returns:
        Tuple[bool, Dict[str, Any]]: (Success status, Results dict)
    """
    log_info("Checking kernel parameters...")
    
    try:
        cmdline_output = run_command("cat /proc/cmdline", debug=debug)
        if cmdline_output is None:
            return False, {"error": "Failed to read kernel cmdline"}
            
        cmdline = cmdline_output.strip()
        log_debug(f"Kernel cmdline: {cmdline}", debug)
        
        # Check for necessary parameters
        amd_iommu = "amd_iommu=on" in cmdline
        intel_iommu = "intel_iommu=on" in cmdline
        iommu_pt = "iommu=pt" in cmdline
        rd_driver_pre = "rd.driver.pre=vfio-pci" in cmdline
        
        # Results
        results = {
            "cmdline": cmdline,
            "amd_iommu": amd_iommu,
            "intel_iommu": intel_iommu,
            "iommu_pt": iommu_pt,
            "rd_driver_pre": rd_driver_pre,
            "any_iommu": amd_iommu or intel_iommu
        }
        
        # Success if either AMD or Intel IOMMU is enabled, and iommu=pt is set
        success = (amd_iommu or intel_iommu) and iommu_pt
        
        if success:
            log_success("Kernel parameters check passed!")
        else:
            log_error("Kernel parameters check failed!")
            missing_params = []
            
            if not (amd_iommu or intel_iommu):
                missing_params.append("amd_iommu=on or intel_iommu=on")
            if not iommu_pt:
                missing_params.append("iommu=pt")
            if not rd_driver_pre:
                missing_params.append("rd.driver.pre=vfio-pci")
                
            log_error(f"Missing parameters: {', '.join(missing_params)}")
            results["missing_params"] = missing_params
            
        return success, results
    
    except Exception as e:
        log_error(f"Error during kernel parameters check: {e}")
        return False, {"error": str(e)}


def _verify_iommu_active(debug: bool = False) -> Tuple[bool, Dict[str, Any]]:
    """Verify that IOMMU is active.
    
    Args:
        debug: Enable debug output
        
    Returns:
        Tuple[bool, Dict[str, Any]]: (Success status, Results dict)
    """
    log_info("Checking if IOMMU is active...")
    
    try:
        dmesg_output = run_command("dmesg | grep -i -e DMAR -e IOMMU", debug=debug)
        if dmesg_output is None:
            return False, {"error": "Failed to run dmesg command"}
            
        log_debug(f"DMESG IOMMU output:\n{dmesg_output}", debug)
        
        # Check for IOMMU initialization messages
        success_patterns = [
            r"AMD-Vi:.*IOMMU.*enabled",
            r"DMAR:.*IOMMU.*enabled",
            r"AMD-Vi: Initialized for Passthrough Mode",
            r"Intel-IOMMU: enabled",
            r"IOMMU:.*initialized"
        ]
        
        error_patterns = [
            r"Failed to enable.*IOMMU",
            r"IOMMU.*not.*detected",
            r"IOMMU.*disabled"
        ]
        
        # Check if any success patterns match
        success_found = any(re.search(pattern, dmesg_output, re.IGNORECASE) for pattern in success_patterns)
        error_found = any(re.search(pattern, dmesg_output, re.IGNORECASE) for pattern in error_patterns)
        
        success = success_found and not error_found
        
        # Check if /sys/kernel/iommu_groups/ has contents
        iommu_groups_cmd = "ls -la /sys/kernel/iommu_groups/ | wc -l"
        iommu_groups_count = run_command(iommu_groups_cmd, debug=debug)
        
        if iommu_groups_count is not None:
            # Subtract 3 for ., .. and total lines
            try:
                group_count = int(iommu_groups_count.strip()) - 3
                group_count = max(0, group_count)  # Ensure not negative
            except ValueError:
                group_count = 0
        else:
            group_count = 0
            
        # Results dictionary
        results = {
            "dmesg_output": dmesg_output,
            "success_matches": success_found,
            "error_matches": error_found,
            "iommu_group_count": group_count
        }
        
        # Additional validation based on group count
        if group_count > 0:
            success = True
            log_success(f"IOMMU seems to be active! Found {group_count} IOMMU groups.")
        elif success:
            log_success("IOMMU activation messages found in dmesg.")
        else:
            log_error("IOMMU does not appear to be active in dmesg output.")
            
        return success, results
    
    except Exception as e:
        log_error(f"Error during IOMMU activation check: {e}")
        return False, {"error": str(e)}


def _verify_iommu_groups(debug: bool = False) -> Tuple[bool, Dict[str, Any]]:
    """Verify IOMMU groups.
    
    Args:
        debug: Enable debug output
        
    Returns:
        Tuple[bool, Dict[str, Any]]: (Success status, Results dict)
    """
    log_info("Checking IOMMU groups...")
    
    try:
        # Use subprocess directly for complex shell commands
        iommu_cmd = "for d in /sys/kernel/iommu_groups/*/devices/*; do " \
                   "n=${d#*/iommu_groups/*}; n=${n%%/*}; " \
                   "printf 'IOMMU Group %s ' \"$n\"; lspci -nns \"${d##*/}\"; " \
                   "done | sort -n -k3"
        
        # Use subprocess.run directly for shell commands
        process = subprocess.run(
            iommu_cmd, 
            shell=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True
        )
        iommu_output = process.stdout
        
        if debug:
            log_debug(f"Running shell command: {iommu_cmd}", debug)
            log_debug(f"Command output: {iommu_output}", debug)
            log_debug(f"Command return code: {process.returncode}", debug)
            if process.stderr:
                log_debug(f"Command stderr: {process.stderr}", debug)
                
        if process.returncode != 0 or not iommu_output.strip():
            return False, {"error": "Failed to get IOMMU groups or none found"}
            
        log_debug(f"IOMMU groups:\n{iommu_output}", debug)
        
        # Count groups and devices
        lines = iommu_output.strip().split('\n')
        group_counts = {}
        for line in lines:
            if line.startswith('IOMMU Group'):
                match = re.search(r'IOMMU Group (\d+)', line)
                if match:
                    group_id = match.group(1)
                    if group_id in group_counts:
                        group_counts[group_id] += 1
                    else:
                        group_counts[group_id] = 1
                        
        # Extract GPU listings (looking for VGA/Display/3D controllers)
        gpu_lines = [line for line in lines if re.search(r'\[(03|01)[0-9][0-9]\]', line)]
        
        results = {
            "iommu_output": iommu_output,
            "group_counts": group_counts,
            "total_groups": len(group_counts),
            "gpu_lines": gpu_lines
        }
        
        if not group_counts:
            log_error("No IOMMU groups found. IOMMU may not be properly enabled.")
            return False, results
            
        log_success(f"Found {len(group_counts)} IOMMU groups.")
        
        # Look for devices with display or GPU functions
        if gpu_lines:
            log_success(f"Found {len(gpu_lines)} GPU-related devices in IOMMU groups.")
        else:
            log_warning("No GPU-related devices found in IOMMU groups.")
            
        # This check can't fully determine if the groups are valid for passthrough
        # since we need to know which GPU the user wants to pass through
        return True, results
    
    except Exception as e:
        log_error(f"Error during IOMMU groups check: {e}")
        return False, {"error": str(e)}


def _verify_vfio_binding(debug: bool = False) -> Tuple[bool, Dict[str, Any]]:
    """Verify that any GPU is bound to vfio-pci driver.
    
    Args:
        debug: Enable debug output
        
    Returns:
        Tuple[bool, Dict[str, Any]]: (Success status, Results dict)
    """
    log_info("Checking GPU driver binding...")
    
    try:
        # Get lspci output with kernel driver information
        lspci_output = run_command("lspci -nnk", debug=debug)
        if lspci_output is None:
            return False, {"error": "Failed to run lspci command"}
            
        log_debug(f"LSPCI output sample (first 10 lines):\n" + 
                 "\n".join(lspci_output.split('\n')[:10]), debug)
        
        # Parse lspci output to find GPUs and their drivers
        lines = lspci_output.split('\n')
        gpus = []
        current_device = None
        
        for line in lines:
            # Check for VGA/Display/3D controller lines
            if re.search(r'VGA|Display|3D controller', line):
                bdf = line.split(' ')[0]  # Bus:Device.Function
                match = re.search(r'\[([\w:]+)\]', line)
                device_id = match.group(1) if match else "unknown"
                description = line
                current_device = {
                    "bdf": bdf,
                    "device_id": device_id,
                    "description": description.strip(),
                    "driver": None,
                    "modules": []
                }
                gpus.append(current_device)
            
            # Check for driver lines for current device
            elif current_device is not None and "Kernel driver in use:" in line:
                current_device["driver"] = line.split("Kernel driver in use:")[1].strip()
                
            # Check for available modules
            elif current_device is not None and "Kernel modules:" in line:
                current_device["modules"] = [m.strip() for m in line.split("Kernel modules:")[1].strip().split()]
                current_device = None  # Reset current device
                
        # Look for at least one GPU bound to vfio-pci
        vfio_bound_gpus = [gpu for gpu in gpus if gpu["driver"] == "vfio-pci"]
        
        results = {
            "gpus": gpus,
            "vfio_bound_gpus": vfio_bound_gpus,
            "total_gpus": len(gpus),
            "vfio_bound_count": len(vfio_bound_gpus)
        }
        
        if vfio_bound_gpus:
            log_success(f"Found {len(vfio_bound_gpus)} GPU(s) bound to vfio-pci driver:")
            for gpu in vfio_bound_gpus:
                log_success(f"  - {gpu['description']} (Driver: vfio-pci)")
            return True, results
        else:
            log_error("No GPUs found bound to vfio-pci driver. VFIO passthrough is not active.")
            if gpus:
                log_info("Found the following GPUs:")
                for gpu in gpus:
                    log_info(f"  - {gpu['description']} (Driver: {gpu['driver'] or 'None'})")
            return False, results
            
    except Exception as e:
        log_error(f"Error during GPU driver binding check: {e}")
        return False, {"error": str(e)}


def _verify_host_gpu(debug: bool = False) -> Tuple[bool, Dict[str, Any]]:
    """Verify that the host has a working GPU.
    
    Args:
        debug: Enable debug output
        
    Returns:
        Tuple[bool, Dict[str, Any]]: (Success status, Results dict)
    """
    log_info("Checking host GPU status...")
    
    try:
        # Get display information - use subprocess directly for shell commands
        xrandr_cmd = "which xrandr >/dev/null 2>&1 && xrandr --listmonitors || echo 'xrandr not available'"
        
        # Use subprocess.run directly for shell commands
        process = subprocess.run(
            xrandr_cmd, 
            shell=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True
        )
        xrandr_output = process.stdout
        
        if debug:
            log_debug(f"Running shell command: {xrandr_cmd}", debug)
            log_debug(f"Command output: {xrandr_output}", debug)
        
        # Get GPU information - this doesn't need shell
        gpu_info_cmd = "lspci -nnk | grep -A3 VGA"
        gpu_info = run_command(gpu_info_cmd, debug=debug)
        
        # Results
        results = {
            "xrandr_output": xrandr_output,
            "gpu_info": gpu_info,
            "display_found": "Monitor" in xrandr_output if xrandr_output else False,
            "has_host_gpu": False
        }
        
        # Check if any non-vfio-pci GPU is available
        if gpu_info:
            lines = gpu_info.split('\n')
            for i in range(len(lines)):
                if "VGA" in lines[i]:
                    # Look for driver in next lines
                    for j in range(i+1, min(i+4, len(lines))):
                        if "Kernel driver in use:" in lines[j] and "vfio-pci" not in lines[j]:
                            driver = lines[j].split("Kernel driver in use:")[1].strip()
                            results["has_host_gpu"] = True
                            results["host_gpu_driver"] = driver
                            log_success(f"Found host GPU using driver: {driver}")
                            break
        
        # Consider the check successful if either:
        # 1. We have display output according to xrandr, or
        # 2. We found a GPU with a non-vfio-pci driver
        success = results["display_found"] or results["has_host_gpu"]
        
        if success:
            log_success("Host GPU check passed!")
        else:
            log_error("Could not verify a working host GPU.")
            log_warning("If you're accessing this system remotely, this may be expected.")
            
        return success, results
    
    except Exception as e:
        log_error(f"Error during host GPU check: {e}")
        return False, {"error": str(e)}


#
# Fix functions for failed verification steps
#

def _fix_kernel_parameters(result: Dict[str, Any], debug: bool = False) -> bool:
    """Fix kernel parameters for VFIO.
    
    Args:
        result: Results from verification step
        debug: Enable debug output
        
    Returns:
        bool: True if fix was successful, False otherwise
    """
    log_info("Attempting to fix kernel parameters...")
    
    # Missing parameters that need to be added
    missing_params = result.get("missing_params", [])
    if not missing_params:
        log_error("No missing parameters to fix.")
        return False
    
    log_info(f"Missing kernel parameters: {', '.join(missing_params)}")
    
    try:
        # Attempt to use the configure_kernel_parameters function
        log_info("This requires updating the bootloader configuration and rebuilding initramfs.")
        log_warning("A system reboot will be required after this fix is applied.")
        
        confirm = input(f"{Colors.YELLOW}Proceed with kernel parameter updates? (y/n): {Colors.ENDC}").lower()
        if confirm != 'y':
            log_info("Kernel parameter fix aborted by user.")
            return False
        
        # Call the existing kernel parameter configuration function
        kernel_param_result = configure_kernel_parameters(dry_run=False, debug=debug)
        
        # Track changes if needed
        changes = {}
        method = kernel_param_result.get("method") if kernel_param_result else None
        status = kernel_param_result.get("status") if kernel_param_result else False
        
        if status and method == "grub" and kernel_param_result.get("backup_path"):
            changes = track_change(
                changes, "files", "/etc/default/grub", "modified", 
                {"backup_path": kernel_param_result.get("backup_path")}
            )
        elif status and method == "kernelstub":
            for param in kernel_param_result.get("added_params", []):
                changes = track_change(changes, "kernelstub", param, "added")
                
        # If kernel parameters were updated, we should also update initramfs
        if status:
            log_info("Kernel parameters updated. Updating initramfs...")
            initramfs_success = update_initramfs(dry_run=False, debug=debug)
            if initramfs_success:
                log_success("Initramfs updated successfully!")
                changes = track_change(changes, "initramfs", "update", "executed")
            else:
                log_error("Initramfs update failed.")
                return False
                
        # Check if changes were successful based on the return value
        if status:
            log_success("Kernel parameters configured successfully!")
            log_warning("A system reboot is required for changes to take effect.")
            return True
        else:
            log_error("Failed to configure kernel parameters.")
            return False
    
    except Exception as e:
        log_error(f"Error while fixing kernel parameters: {e}")
        return False


def _fix_iommu_active(result: Dict[str, Any], debug: bool = False) -> bool:
    """Fix IOMMU activation.
    
    Args:
        result: Results from verification step
        debug: Enable debug output
        
    Returns:
        bool: True if fix was successful, False otherwise
    """
    log_info("Attempting to fix IOMMU activation...")
    
    # This generally requires the same fix as kernel parameters
    log_warning("IOMMU activation requires proper kernel parameters and a system reboot.")
    log_info("This will configure all required kernel parameters for IOMMU.")
    
    # Use the same fix as for kernel parameters
    return _fix_kernel_parameters({"missing_params": ["amd_iommu=on", "iommu=pt"]}, debug)


def _fix_iommu_groups(result: Dict[str, Any], debug: bool = False) -> bool:
    """Fix IOMMU groups issues.
    
    Args:
        result: Results from verification step
        debug: Enable debug output
        
    Returns:
        bool: True if fix was successful, False otherwise
    """
    log_info("IOMMU group issues can be complex to fix automatically.")
    log_info("Common causes include:")
    log_info("1. IOMMU not enabled in kernel parameters")
    log_info("2. IOMMU not supported by hardware")
    log_info("3. Poor IOMMU implementation requiring ACS override patch")
    
    # Check if we have any IOMMU groups at all
    if result.get("total_groups", 0) == 0:
        log_info("No IOMMU groups found. Likely needs kernel parameter fix.")
        return _fix_kernel_parameters({"missing_params": ["amd_iommu=on", "iommu=pt"]}, debug)
    
    # If we have groups but no GPUs, more complex issues may be at play
    log_warning("IOMMU groups exist but may have issues with GPU isolation.")
    log_warning("This might require ACS override patches (unsafe) or using a different PCI slot.")
    log_info("No automated fix is available for this specific issue.")
    
    return False


def _fix_vfio_binding(result: Dict[str, Any], debug: bool = False) -> bool:
    """Fix VFIO driver binding.
    
    Args:
        result: Results from verification step
        debug: Enable debug output
        
    Returns:
        bool: True if fix was successful, False otherwise
    """
    log_info("Attempting to fix VFIO driver binding...")
    
    gpus = result.get("gpus", [])
    if not gpus:
        log_error("No GPUs detected. Cannot fix VFIO binding.")
        return False
    
    # Check if there are multiple GPUs
    if len(gpus) < 2:
        log_warning("Only one GPU detected. Binding it to VFIO may cause display loss.")
        confirm = input(f"{Colors.YELLOW}Continue anyway? This may cause your display to stop working. (y/n): {Colors.ENDC}").lower()
        if confirm != 'y':
            log_info("VFIO binding fix aborted by user.")
            return False
    
    # Let user select which GPU to passthrough
    print(f"\n{Colors.BOLD}Available GPUs:{Colors.ENDC}")
    for i, gpu in enumerate(gpus):
        print(f"{i+1}. {gpu['description']} (current driver: {gpu['driver'] or 'None'})")
    
    # Get user selection
    try:
        selection = int(input(f"\n{Colors.YELLOW}Enter the number of the GPU to bind to VFIO-PCI: {Colors.ENDC}"))
        if selection < 1 or selection > len(gpus):
            log_error("Invalid selection.")
            return False
            
        selected_gpu = gpus[selection-1]
        log_info(f"Selected GPU: {selected_gpu['description']}")
        
        # Extract vendor:device ID
        device_id_match = re.search(r'\[([\w:]+)\]', selected_gpu['description'])
        if not device_id_match:
            log_error("Could not extract device ID from GPU description.")
            return False
            
        device_id = device_id_match.group(1)
        log_info(f"Device ID: {device_id}")
        
        # Use the configure_vfio_modprobe function to setup VFIO
        vfio_success = configure_vfio_modprobe([device_id], dry_run=False, debug=debug)
        
        if vfio_success:
            log_success("VFIO driver configuration completed successfully.")
            log_warning("A system reboot is required for changes to take effect.")
            
            # Also update initramfs
            log_info("Updating initramfs to include changes...")
            initramfs_success = update_initramfs(dry_run=False, debug=debug)
            if initramfs_success:
                log_success("Initramfs update completed successfully.")
            else:
                log_error("Initramfs update failed.")
                return False
                
            return True
        else:
            log_error("VFIO driver configuration failed.")
            return False
    
    except ValueError:
        log_error("Invalid input. Please enter a number.")
        return False
    except Exception as e:
        log_error(f"Error during VFIO binding fix: {e}")
        return False


def _fix_host_gpu(result: Dict[str, Any], debug: bool = False) -> bool:
    """Fix host GPU issues.
    
    Args:
        result: Results from verification step
        debug: Enable debug output
        
    Returns:
        bool: True if fix was successful, False otherwise
    """
    log_info("Host GPU issues are difficult to fix automatically.")
    log_info("Common causes include:")
    log_info("1. The only GPU is bound to VFIO-PCI")
    log_info("2. Display driver is not loaded correctly")
    
    # Simple check: if we have multiple GPUs but all are bound to VFIO
    if result.get("has_host_gpu", False):
        log_info("A host GPU with a driver was detected, but display may not be working.")
        log_info("This could be a configuration issue with your display manager or X server.")
    else:
        log_info("No host GPU with a proper driver was detected.")
        log_warning("If all GPUs are bound to VFIO, you may need to leave one for the host.")
    
    log_warning("No automated fix is available for this issue.")
    log_info("Consider modifying your VFIO configuration to exclude one GPU for host use.")
    
    return False


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