#!/usr/bin/env python3
"""
Guardrails Engine
Central orchestrator for all guardrail checks. Blocks secrets, enforces
package policies, validates folder structure, and handles human escalation.
"""
import os
import sys
import json
import yaml
import logging
from pathlib import Path
from datetime import datetime

from secrets_scanner import SecretsScanner
from package_manager import PackageManager
from folder_validator import FolderValidator
from human_input_handler import HumanInputHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("guardrails-engine")


class GuardrailsResult:
    def __init__(self):
        self.passed = True
        self.violations: list[dict] = []
        self.warnings: list[dict] = []
        self.human_escalations: list[dict] = []
        self.auto_fixes: list[dict] = []
        self.timestamp = datetime.utcnow().isoformat()

    def add_violation(self, rule: str, message: str, file: str = None,
                      line: int = None, severity: str = "error"):
        self.passed = False
        self.violations.append({
            "rule": rule,
            "severity": severity,
            "message": message,
            "file": file,
            "line": line
        })

    def add_warning(self, rule: str, message: str, file: str = None):
        self.warnings.append({"rule": rule, "message": message, "file": file})

    def add_escalation(self, reason: str, context: dict):
        self.human_escalations.append({"reason": reason, "context": context})

    def add_fix(self, description: str, details: dict):
        self.auto_fixes.append({"description": description, "details": details})

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "timestamp": self.timestamp,
            "summary": {
                "violations": len(self.violations),
                "warnings": len(self.warnings),
                "escalations": len(self.human_escalations),
                "auto_fixes": len(self.auto_fixes)
            },
            "violations": self.violations,
            "warnings": self.warnings,
            "human_escalations": self.human_escalations,
            "auto_fixes": self.auto_fixes
        }

    def print_report(self):
        status = "PASSED" if self.passed else "FAILED"
        border = "=" * 60
        print(f"\n{border}")
        print(f"  GUARDRAILS REPORT: {status}")
        print(f"  Checked: {self.timestamp}")
        print(border)

        if self.violations:
            print(f"\n🚫 VIOLATIONS ({len(self.violations)}):")
            for v in self.violations:
                loc = f" [{v['file']}:{v['line']}]" if v.get('line') else \
                      f" [{v['file']}]" if v.get('file') else ""
                print(f"  [{v['severity'].upper()}] {v['rule']}{loc}")
                print(f"    {v['message']}")

        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for w in self.warnings:
                loc = f" [{w['file']}]" if w.get('file') else ""
                print(f"  {w['rule']}{loc}: {w['message']}")

        if self.auto_fixes:
            print(f"\n🔧 AUTO-FIXES APPLIED ({len(self.auto_fixes)}):")
            for f in self.auto_fixes:
                print(f"  ✓ {f['description']}")

        if self.human_escalations:
            print(f"\n👤 HUMAN ESCALATION REQUIRED ({len(self.human_escalations)}):")
            for e in self.human_escalations:
                print(f"  ! {e['reason']}")

        print(f"\n{border}\n")


class GuardrailsEngine:
    """
    Main guardrails orchestrator. Loads config and runs all checks.
    """

    def __init__(self, config_path: str = None):
        config_path = config_path or os.environ.get(
            "GUARDRAILS_CONFIG",
            str(Path(__file__).parent.parent / "config" / "guardrails_config.yaml")
        )
        self.config = self._load_config(config_path)
        self.result = GuardrailsResult()

        self.secrets_scanner = SecretsScanner(self.config.get("secrets", {}))
        self.package_manager = PackageManager(self.config.get("packages", {}))
        self.folder_validator = FolderValidator(self.config.get("folder_structure", {}))
        self.human_handler = HumanInputHandler(self.config.get("human_input", {}))

    def _load_config(self, path: str) -> dict:
        try:
            with open(path) as f:
                cfg = yaml.safe_load(f)
            logger.info(f"Loaded guardrails config from {path}")
            return cfg
        except FileNotFoundError:
            logger.warning(f"Config not found at {path}, using defaults")
            return {}
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in config: {e}")
            return {}

    def run(self, target_path: str = ".", mode: str = "check") -> GuardrailsResult:
        """
        Run all guardrail checks against the given path.
        mode: 'check' (report only) | 'fix' (auto-fix where possible) | 'block' (exit on fail)
        """
        logger.info(f"Running guardrails on '{target_path}' in '{mode}' mode")
        target = Path(target_path).resolve()

        # 1. Secrets scan
        self._run_secrets_check(target)

        # 2. Package policy
        self._run_package_check(target)

        # 3. Folder structure validation
        self._run_folder_check(target, mode)

        # 4. Human escalation check
        self._run_human_escalation_check()

        # 5. Print report
        self.result.print_report()

        # Save JSON report
        report_path = target / ".guardrails-report.json"
        with open(report_path, "w") as f:
            json.dump(self.result.to_dict(), f, indent=2)
        logger.info(f"Report saved to {report_path}")

        if mode == "block" and not self.result.passed:
            logger.error("Guardrails FAILED. Blocking operation.")
            sys.exit(1)

        return self.result

    def _run_secrets_check(self, target: Path):
        logger.info("Running secrets scan...")
        findings = self.secrets_scanner.scan_directory(str(target))
        for finding in findings:
            if finding["severity"] == "critical":
                self.result.add_violation(
                    rule="NO_SECRETS",
                    message=f"Secret detected: {finding['description']}. "
                            f"Remove it and rotate the credential immediately.",
                    file=finding.get("file"),
                    line=finding.get("line"),
                    severity="critical"
                )
                # Always escalate secret violations to humans
                self.result.add_escalation(
                    reason=f"Critical secret found in {finding.get('file', 'unknown file')}. "
                           f"Human review and credential rotation required.",
                    context=finding
                )
            else:
                self.result.add_warning(
                    rule="POSSIBLE_SECRET",
                    message=finding["description"],
                    file=finding.get("file")
                )

    def _run_package_check(self, target: Path):
        logger.info("Running package policy check...")
        findings = self.package_manager.check(str(target))

        for finding in findings:
            ftype = finding["type"]
            if ftype == "pinned_to_exact":
                self.result.add_warning(
                    rule="PACKAGE_VERSION_POLICY",
                    message=f"Package '{finding['package']}' is pinned to exact version "
                            f"'{finding['version']}'. Consider using '{finding['suggested']}'.",
                    file=finding.get("file")
                )
            elif ftype == "outdated":
                self.result.add_warning(
                    rule="OUTDATED_PACKAGE",
                    message=f"Package '{finding['package']}' is outdated. "
                            f"Current: {finding['current']}, Latest: {finding['latest']}.",
                    file=finding.get("file")
                )
                # Ask human if major version bump
                if finding.get("is_major_bump"):
                    self.result.add_escalation(
                        reason=f"Major version upgrade for '{finding['package']}' "
                               f"({finding['current']} → {finding['latest']}) requires human approval.",
                        context=finding
                    )
            elif ftype == "vulnerable":
                self.result.add_violation(
                    rule="VULNERABLE_PACKAGE",
                    message=f"Package '{finding['package']}' has known vulnerability "
                            f"{finding.get('cve', 'unknown')}. Upgrade to {finding.get('safe_version')}.",
                    file=finding.get("file"),
                    severity="critical"
                )
                self.result.add_escalation(
                    reason=f"Vulnerable package '{finding['package']}' requires immediate human attention.",
                    context=finding
                )
            elif ftype == "auto_fixed":
                self.result.add_fix(
                    description=f"Auto-upgraded '{finding['package']}' "
                                f"from {finding['old_version']} to {finding['new_version']}",
                    details=finding
                )

    def _run_folder_check(self, target: Path, mode: str):
        logger.info("Running folder structure validation...")
        findings = self.folder_validator.validate(str(target))

        for finding in findings:
            ftype = finding["type"]
            if ftype == "missing_required":
                self.result.add_violation(
                    rule="FOLDER_STRUCTURE",
                    message=f"Required path missing: '{finding['path']}'. "
                            f"Industry standard requires this structure.",
                    file=finding.get("path"),
                    severity="error"
                )
                if mode == "fix" and finding.get("can_auto_create"):
                    Path(target / finding["path"]).mkdir(parents=True, exist_ok=True)
                    self.result.add_fix(
                        description=f"Created missing directory: {finding['path']}",
                        details=finding
                    )
            elif ftype == "wrong_location":
                self.result.add_violation(
                    rule="FILE_PLACEMENT",
                    message=f"File '{finding['file']}' is in wrong location. "
                            f"Expected: {finding['expected_location']}.",
                    severity="warning"
                )
            elif ftype == "naming_convention":
                self.result.add_warning(
                    rule="NAMING_CONVENTION",
                    message=f"'{finding['path']}' does not follow naming convention. "
                            f"Expected: {finding['expected_pattern']}",
                    file=finding.get("path")
                )

    def _run_human_escalation_check(self):
        """Trigger human Q&A for critical decisions."""
        if not self.result.human_escalations:
            return

        if self.human_handler.is_interactive():
            logger.info("Triggering human escalation Q&A...")
            responses = self.human_handler.prompt_for_escalations(
                self.result.human_escalations
            )
            for escalation, response in zip(self.result.human_escalations, responses):
                escalation["human_response"] = response
                escalation["resolved"] = response.get("approved", False)
        else:
            logger.warning(
                "Non-interactive mode: human escalations logged but not resolved. "
                "Set GUARDRAILS_INTERACTIVE=true for interactive mode."
            )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="IT Agents Guardrails Engine")
    parser.add_argument("path", nargs="?", default=".", help="Path to check")
    parser.add_argument("--mode", choices=["check", "fix", "block"], default="check")
    parser.add_argument("--config", help="Path to guardrails config YAML")
    args = parser.parse_args()

    engine = GuardrailsEngine(config_path=args.config)
    engine.run(target_path=args.path, mode=args.mode)
