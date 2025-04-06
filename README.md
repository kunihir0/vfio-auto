# run-vfio.py // connecting worlds... ʕ•ᴥ•ʔ

Present day, present time.

Are you connected? To the other side? This little script helps bridge the gap... connect your GPU from *this* layer (your host system) to *another* layer (a virtual machine). For games, maybe? Or other experiments... ✨

## // What This Signal Does

*   Checks your system's potential (IOMMU, CPU Virtualization). 💻
*   Configures the pathways (`vfio` kernel modules). 🔧
*   Adjusts the boot sequence (GRUB, systemd-boot, Pop!_OS kernelstub). ⚙️
*   Binds your GPU to the VFIO protocol for clean transmission. 🔄
*   Validates IOMMU groups for proper device isolation. 🧩
*   Generates a way back (`vfio_cleanup.sh`) if you get lost. ↩️
*   Creates system snapshots on BTRFS filesystems for safety. 📸
*   Verifies your connection after reboot with repair options. ✅
*   Warns about Secure Boot interference.

## // Protocol Requirements

*   `sudo` / root access (Admin Level Connection).
*   Python 3.6+ (Wired Language Interface v3.6 or higher).
*   Hardware Compatibility (At least two GPUs - one to stay in this layer, one to transmit).
*   IOMMU-capable motherboard with CPU virtualization enabled (Layer Separation Technology).
*   Supported bootloader (GRUB, systemd-boot, Pop!_OS kernelstub).

## // Initiate Connection

It's simple. Just... reach out.

```bash
sudo ./run-vfio.py
```

## // Connection Parameters

*   `--dry-run` ➡️ Simulate the connection. No real changes made. Safe~ ☆
*   `--cleanup` ➡️ Disconnect. Runs the generated vfio_cleanup.sh if it exists.
*   `--debug` ➡️ Show all the hidden signals. Can be noisy. 📡
*   `--verify` ➡️ Check if your system is properly configured after reboot. 🔍
*   `--verify-auto` ➡️ Interactive verification with automated repair options. 🛠️
*   `--non-interactive` ➡️ Assume "yes" to all prompts. For automated scripts. 🤖
*   `--output-dir PATH` ➡️ Custom directory for generated files. 📁
*   `--help` ➡️ Show all possible connection parameters. 💬

## // Signal Interference ⚠️

Modifying system connections can be strange. Unexpected results may occur. This script tries to be careful (backups, cleanup script), but the Wired is complex. Use --dry-run first. Understand what you are doing.

Secure Boot can disrupt the connection. Virtualization must be enabled in BIOS/UEFI. Poor IOMMU grouping may require unsafe ACS override patches. Sometimes, layer separation isn't clean.

## // Protocol Architecture

The signal is modular:
*   `vfio_configurator/` ➡️ The main transmission protocol modules
*   `pci.py` ➡️ Discovers devices and their IOMMU groupings
*   `reporting.py` ➡️ Creates visual signals about your system status
*   `bootloader.py` ➡️ Configures your system's initialization sequence
*   `initramfs.py` ➡️ Updates your system's boot image with required modules
*   `vfio_mods.py` ➡️ Handles VFIO driver configuration
*   `checks.py` ➡️ Verifies system compatibility and requirements
*   `snapshot.py` ➡️ Creates BTRFS snapshots for recovery
*   `state.py` ➡️ Tracks changes and generates cleanup script

...No matter where you go, everyone's connected.

## // Distribution Support

The protocol attempts to adapt to various layers of reality:
*   Debian-based (Ubuntu, Pop!_OS, Linux Mint, elementary OS)
*   Arch-based (Manjaro, EndeavourOS, Garuda)
*   Fedora-based (RHEL, CentOS, Rocky, AlmaLinux)
*   openSUSE / SUSE

Each realm has unique pathways, but the signal tries to find its way through.