"""A tiny smoke test for this cloud development environment.

Run from the repository directory:
    python3 hello_cloud.py

This script uses only Python's standard library; no installation is needed.
"""

import platform


def main():
    print("Hello from the cloud environment!")
    print(f"Python {platform.python_version()} is running on {platform.system()}.")
    print("Success: this repository's Python script executed correctly.")


if __name__ == "__main__":
    main()
