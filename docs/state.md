# State Module (`vfio_configurator/state.py`)

The `state.py` module is a crucial component of `vfio-auto`, providing the framework for tracking all changes made to the system and enabling a reliable cleanup process. Its main purpose is to ensure that every modification can be reverted, providing a safety net for the user.

## Key Functions

### `track_change()`

This function is called from various parts of the application whenever a change is made to the system. It records a detailed entry for each modification, including:

-   **Category**: The type of change (e.g., `files`, `kernelstub`, `modules`).
-   **Target**: The specific file or item that was modified.
-   **Action**: The operation performed (e.g., `modified`, `created`, `added`).
-   **Details**: A dictionary containing any relevant metadata, such as the path to a backup file.

### `create_cleanup_script()`

Once the setup process is complete, this function takes the dictionary of tracked changes and generates a shell script named `vfio_cleanup.sh`. This script contains the necessary commands to reverse every change that was made. For example:

-   If a file was modified, the cleanup script will copy the backup file back to its original location.
-   If a file was created, the cleanup script will delete it.
-   If a kernel parameter was added with `kernelstub`, the cleanup script will use `kernelstub` to remove it.

### `SystemState` Class

This class acts as a container for the application's state, holding both the gathered system information and the record of changes. It provides a centralized place to manage the data that drives the configuration and cleanup processes.

## The Cleanup Process

The generation of a cleanup script is a cornerstone of `vfio-auto`'s design philosophy. By creating a self-contained, executable script, the tool empowers the user to easily and reliably undo the setup. This is particularly important for a process as complex as VFIO configuration, where a mistake could potentially lead to an unbootable system. The cleanup script ensures that there is always a clear path back to the original state.