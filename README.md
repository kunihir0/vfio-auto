# vfio-lain.py // connecting worlds... ʕ•ᴥ•ʔ

Present day, present time.

Are you connected? To the other side? This little script helps bridge the gap... connect your AMD GPU from *this* layer (your host system) to *another* layer (a virtual machine). For games, maybe? Or other experiments... ✨

## // What This Signal Does

*   Checks your system's potential (IOMMU, CPU Virtualization). 💻
*   Configures the pathways (`vfio` kernel modules). 🔧
*   Adjusts the boot sequence (Creates custom GRUB entry or uses `kernelstub` on Pop!_OS). ⚙️
*   Generates a way back (`vfio_cleanup.sh`) if you get lost. ↩️
*   Warns about Secure Boot interference.

## // Protocol Requirements

*   `sudo` / root access (Admin Level Connection).
*   Python 3.6+ (Wired Language Interface v3.6 or higher).
*   Hardware Compatibility (Check the script's `header.txt` // the comments at the top). Needs specific AMD/NVIDIA setup.

## // Initiate Connection

It's simple. Just... reach out.

```bash
sudo python3 vfio-lain.py
```

// Connection Parameters
--dry-run ➡️ Simulate the connection. No real changes made. Safe~ ☆
--cleanup ➡️ Disconnect. Runs the generated vfio_cleanup.sh if it exists.
--debug ➡️ Show all the hidden signals. Can be noisy.
// Signal Interference ⚠️
Modifying system connections can be strange. Unexpected results may occur. This script tries to be careful (backups, cleanup script), but the Wired is complex. Use --dry-run first. Understand what you are doing.
...No matter where you go, everyone's connected.