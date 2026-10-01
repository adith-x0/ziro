import subprocess
import sys
from pathlib import Path


def run_command(cmd, desc):
    print(f"\n---> Running: {desc} ({' '.join(cmd)})")
    res = subprocess.run(cmd, cwd=Path(__file__).resolve().parent.parent)
    if res.returncode != 0:
        print(f"[ERROR] {desc} failed with exit code {res.returncode}")
        return False
    print(f"[SUCCESS] {desc} passed.")
    return True


def main():
    print("=" * 60)
    print("NEXUS Automated Quality & Verification Checks")
    print("=" * 60)

    python_exe = sys.executable
    success = True

    # 1. Ruff linting
    success &= run_command([python_exe, "-m", "ruff", "check", "."], "Ruff Linting")

    # 2. Ruff formatting check
    success &= run_command(
        [python_exe, "-m", "ruff", "format", "--check", "."], "Ruff Format Check"
    )

    # 3. Mypy type check
    success &= run_command(
        [python_exe, "-m", "mypy", "backend/app", "database", "agents", "tools", "orchestration"],
        "Mypy Type Checking",
    )

    # 4. Pytest test suite
    success &= run_command([python_exe, "-m", "pytest", "tests"], "Pytest Test Suite")

    print("\n" + "=" * 60)
    if success:
        print("ALL CHECKS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("SOME CHECKS FAILED. See output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
