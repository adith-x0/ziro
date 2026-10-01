import importlib
import sys
from pathlib import Path


def check_runtime():
    print(f"Python Version: {sys.version}")
    assert sys.version_info >= (3, 11), "Python 3.11+ required!"
    print("  [OK] Python version requirement met.")


def check_packages():
    required_packages = [
        "fastapi",
        "pydantic",
        "pydantic_settings",
        "httpx",
        "sqlalchemy",
        "pytest",
    ]
    print("\nChecking core packages:")
    for pkg in required_packages:
        try:
            mod = importlib.import_module(pkg)
            version = getattr(mod, "__version__", "unknown")
            print(f"  [OK] {pkg} (version: {version})")
        except ImportError:
            print(f"  [FAIL] Missing package: {pkg}")


def check_directories():
    base_dir = Path(__file__).resolve().parent.parent
    required_dirs = [
        "backend",
        "frontend",
        "agents",
        "tools",
        "orchestration",
        "database",
        "tests",
        "data",
        "docs",
        "scripts",
    ]
    print(f"\nChecking directory structure at {base_dir}:")
    for d in required_dirs:
        path = base_dir / d
        if path.is_dir():
            print(f"  [OK] {d}/")
        else:
            print(f"  [FAIL] Missing directory: {d}/")


if __name__ == "__main__":
    print("=" * 60)
    print("NEXUS Environment Verification")
    print("=" * 60)
    check_runtime()
    check_directories()
    check_packages()
    print("\nVerification complete.")
