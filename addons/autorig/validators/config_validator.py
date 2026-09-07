"""addons/autorig/config_validator.py

Static pre-build validation suite for autorig configuration files.
"""

from typing import Dict, Any, List, Tuple, Callable, Optional, Set
import re
from .. import naming


class ConfigValidationError(Exception):
    """Raised when one or more configuration validation rules fail."""
    pass


class ValidationResult:
    def __init__(self, check_name: str):
        self.check_name: str = check_name
        self.errors: List[str] = []
        self.warnings: List[str] = []

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


class ConfigValidator:
    """Executes registered validation rules and halts the build on failure."""

    def __init__(self, config: Dict[str, Any]):
        self.config: Dict[str, Any] = config
        self._checks: List[Callable[[Dict[str, Any]], ValidationResult]] = []

    def register_check(self, func: Callable[[Dict[str, Any]], ValidationResult]) -> None:
        self._checks.append(func)

    def run(self, verbose: bool = True) -> None:
        results: List[ValidationResult] = []
        failed = False

        print("\n" + "=" * 60)
        print(" [AUTORIG] PRE-BUILD CONFIGURATION VALIDATION")
        print("=" * 60)

        for check_fn in self._checks:
            res = check_fn(self.config)
            results.append(res)

            status = "[PASS]" if res.passed else "[FAIL]"
            print(f"{status} - {res.check_name}")

            for warn in res.warnings:
                print(f"    ! WARNING: {warn}")

            if not res.passed:
                failed = True
                for err in res.errors:
                    print(f"    X ERROR: {err}")

        print("=" * 60 + "\n")

        if failed:
            total_errors = sum(len(r.errors) for r in results)
            raise ConfigValidationError(
                f"Config validation failed with {total_errors} error(s). "
                f"Aborting rig build before modifying armature."
            )