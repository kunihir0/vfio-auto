"""Utility functions for VFIO configuration."""

import os
import re
import shutil
import functools
import subprocess
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Callable

# Cache for frequently accessed system information
_SYSTEM_CACHE: Dict[str, Any] = {}


class Colors:
    """Terminal colors for better readability."""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    ENDC = '\033[0m'


def log_info(message: str) -> None:
    """Print an informational message."""
    print(f"{Colors.BLUE}{Colors.BOLD}[INFO]{Colors.ENDC} {message}")


def log_success(message: str) -> None:
    """Print a success message."""
    print(f"{Colors.GREEN}{Colors.BOLD}[SUCCESS]{Colors.ENDC} {message}")


def log_warning(message: str) -> None:
    """Print a warning message."""
    print(f"{Colors.YELLOW}{Colors.BOLD}[WARNING]{Colors.ENDC} {message}")


def log_error(message: str) -> None:
    """Print an error message."""
    print(f"{Colors.RED}{Colors.BOLD}[ERROR]{Colors.ENDC} {message}")


def log_debug(message: str, debug: bool = False) -> None:
    """Print a debug message if debug mode is enabled."""
    if debug:
        print(f"{Colors.BLUE}[DEBUG]{Colors.ENDC} {message}")


def cached_result(key: str):
    """Decorator to cache function results.
    
    Args:
        key: Base key for the cache entry
        
    Returns:
        Decorated function that caches its result
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = key
            # Include args/kwargs in cache key if needed
            if args or kwargs:
                # Include boolean flags in key explicitly for debug changes
                arg_strs = [str(a) for a in args]
                kwarg_strs = [f"{k}={v}" for k, v in sorted(kwargs.items())]
                cache_key += f"_{'_'.join(arg_strs)}_{'_'.join(kwarg_strs)}"

            if cache_key not in _SYSTEM_CACHE:
                _SYSTEM_CACHE[cache_key] = func(*args, **kwargs)
            return _SYSTEM_CACHE[cache_key]
        return wrapper
    return decorator


def run_command(command: str, dry_run: bool = False, debug: bool = False) -> Optional[str]:
    """Run a shell command and return its output.
    
    Args:
        command: The command to run
        dry_run: If True, don't actually execute commands that modify the system
        debug: If True, print additional debug information
        
    Returns:
        Command output as string or None if command failed
    """
    if dry_run:
        log_debug(f"[DRY RUN] Would run command: {command}", debug)
        # For certain read-only commands, we can still execute them in dry run mode
        read_only_prefixes = ('grep ', 'lspci ', 'ls ', 'df ', 'cat ', 'find ', 'test ', '[ ', 'uname ',
                             'mokutil ', 'findmnt ', 'cmp ', 'dmesg ', 'id ')
        is_read_only = False
        for prefix in read_only_prefixes:
            if command.startswith(prefix):
                is_read_only = True
                break
        # Special case: kernelstub -p is read-only
        if 'kernelstub -p' in command:
            is_read_only = True

        if is_read_only:
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    errors='ignore'  # Ignore potential decoding errors
                )
                log_debug(f"[DRY RUN] Command output (simulated read): {result.stdout.strip()}", debug)
                return result.stdout.strip()
            except subprocess.CalledProcessError as e:
                log_debug(f"[DRY RUN] Command (simulated read) would have failed: {e.stderr.strip()}", debug)
                return None
            except FileNotFoundError:
                log_debug(f"[DRY RUN] Command (simulated read) not found: {command.split()[0]}", debug)
                return None
        else:
            # Simulate success for commands that would modify the system
            return "DRY-RUN-SUCCESS"

    # Special handling for kernelstub
    if 'kernelstub' in command:
        log_debug(f"Running kernelstub command: {command}", debug)
        # Ensure sudo is present if needed
        try:
            result = subprocess.run(
                command,
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors='ignore'
            )
            log_debug(f"Kernelstub command output: {result.stdout.strip()}", debug)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            log_error(f"Kernelstub command failed: {command}")
            log_error(f"Stderr: {e.stderr.strip()}")
            log_debug(f"Stdout: {e.stdout.strip()}", debug)
            return None
        except FileNotFoundError:
            log_error(f"Kernelstub command not found: {command.split()[0]}")
            return None
        except Exception as e:
            log_error(f"Unexpected error running kernelstub command '{command}': {e}")
            return None

    # Standard handling for other commands
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors='ignore'
        )
        if debug:
            log_debug(f"Command output: {result.stdout.strip()}", debug)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {command}")
        log_error(f"Stderr: {e.stderr.strip()}")
        log_debug(f"Stdout: {e.stdout.strip()}", debug)  # Show stdout on error too if debugging
        return None
    except FileNotFoundError:
        log_error(f"Command not found: {command.split()[0]}")
        return None
    except Exception as e:
        log_error(f"Unexpected error running command '{command}': {e}")
        return None


def create_timestamped_backup(file_path_str: str, dry_run: bool = False, debug: bool = False, output_dir: str = None) -> Optional[str]:
    """Create a timestamped backup of a file.
    
    Args:
        file_path_str: Path to the file to back up
        dry_run: If True, don't actually create the backup
        debug: If True, print additional debug information
        output_dir: Directory to store backups (if None, use project root directory)
        
    Returns:
        Path to the backup file or None if backup wasn't needed/created
    """
    file_path = Path(file_path_str)
    if not file_path.exists():
        log_debug(f"File {file_path} does not exist, no backup needed", debug)
        return None

    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    
    # Determine backup directory - use output_dir if provided
    if output_dir:
        backup_dir = Path(output_dir) / "backups"
    else:
        # Use script directory or current directory as fallback
        script_dir = get_script_dir()
        backup_dir = Path(script_dir) / "backups"
    
    # Create backups directory if it doesn't exist
    if not dry_run:
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log_error(f"Could not create backups directory {backup_dir}: {e}")
            return None
    
    # Create a safe filename from the original path to avoid conflicts
    # Convert absolute path to a structure that preserves directories but is safe as a filename
    rel_path = str(file_path).replace('/', '_').replace('\\', '_').lstrip('_')
    backup_filename = f"{rel_path}.vfio_bak.{timestamp}"
    backup_path = backup_dir / backup_filename
    backup_path_str = str(backup_path)

    if dry_run:
        log_debug(f"[DRY RUN] Would create backup of {file_path_str} to {backup_path_str}", debug)
        # In dry-run, return the *intended* backup path so cleanup script knows what it would have been
        return backup_path_str

    try:
        shutil.copy2(file_path_str, backup_path_str)  # copy2 preserves metadata
        log_info(f"Created backup of {file_path_str} to {backup_path_str}")
        return backup_path_str
    except Exception as e:
        log_error(f"Failed to create backup of {file_path_str}: {str(e)}")
        return None


def backup_file(file_path: str, dry_run: bool = False, debug: bool = False, output_dir: str = None) -> Optional[str]:
    """Create a backup of a file.
    
    Args:
        file_path: Path to the file to back up
        dry_run: If True, don't actually create the backup
        debug: If True, print additional debug information
        output_dir: Directory to store backups (if None, use project root directory)
        
    Returns:
        Path to the backup file or None if backup wasn't created
    """
    # This is a wrapper around create_timestamped_backup for backward compatibility
    return create_timestamped_backup(file_path, dry_run, debug, output_dir)


def get_script_dir() -> str:
    """Get the directory where the script is located.
    
    Returns:
        Path to the script directory
    """
    # This should be imported from __main__ or defined at the module level
    # For now we'll use the current working directory as a fallback
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except:
        return os.getcwd()


def get_distro_info():
    """
    Get information about the current Linux distribution.
    
    Returns:
        dict: A dictionary containing distribution information with keys like
              'id', 'name', 'version', etc.
    """
    distro_info = {}
    
    try:
        with open('/etc/os-release', 'r') as f:
            for line in f:
                if '=' in line:
                    key, value = line.rstrip().split('=', 1)
                    # Remove quotes if present
                    value = value.strip('"\'')
                    distro_info[key.lower()] = value
    except FileNotFoundError:
        # Fallback for systems without /etc/os-release
        import platform
        distro_info = {
            'id': platform.system().lower(),
            'name': platform.system(),
            'version': platform.version(),
            'pretty_name': f"{platform.system()} {platform.version()}"
        }
    
    return distro_info