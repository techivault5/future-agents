#!/usr/bin/env python3
"""
Human Input Handler
Manages human-in-the-loop escalations when guardrails are triggered.
Supports interactive CLI Q&A, webhook notifications, and structured approval flows.
"""
import os
import sys
import json
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone


class HumanInputHandler:
    def __init__(self, config: dict = None):
        cfg = config or {}
        self.interactive = cfg.get("interactive", True)
        self.webhook_url = cfg.get("webhook_url") or os.environ.get("GUARDRAILS_WEBHOOK_URL")
        self.slack_webhook = cfg.get("slack_webhook") or os.environ.get("GUARDRAILS_SLACK_WEBHOOK")
        self.approval_timeout_secs = cfg.get("approval_timeout_secs", 300)
        self.log_file = cfg.get("log_file", ".guardrails-human-log.jsonl")
        self.non_interactive_default = cfg.get("non_interactive_default", "deny")

    def is_interactive(self) -> bool:
        """Check if we're in an interactive terminal."""
        return (
            self.interactive
            and sys.stdin.isatty()
            and os.environ.get("GUARDRAILS_INTERACTIVE", "true").lower() == "true"
        )

    def prompt_for_escalations(self, escalations: list) -> list:
        """Prompt the human for each escalation item. Returns list of response dicts."""
        responses = []
        for i, escalation in enumerate(escalations, 1):
            response = self._prompt_single(i, len(escalations), escalation)
            self._log_decision(escalation, response)
            responses.append(response)

            # Send notification if configured
            if self.webhook_url or self.slack_webhook:
                self._send_notification(escalation, response)

        return responses

    def _prompt_single(self, index: int, total: int, escalation: dict) -> dict:
        """Prompt human for a single escalation."""
        reason = escalation.get("reason", "Guardrail triggered")
        context = escalation.get("context", {})

        border = "─" * 60
        print(f"\n{border}")
        print(f"  HUMAN INPUT REQUIRED  ({index}/{total})")
        print(border)
        print(f"\n  Reason: {reason}")

        if context:
            print("\n  Context:")
            for k, v in context.items():
                if k not in ("rule_id", "is_example_file"):
                    print(f"    {k}: {v}")

        # Determine question type from escalation
        question_type = escalation.get("question_type", "approve")
        return self._ask_question(reason, question_type, context)

    def _ask_question(self, reason: str, question_type: str, context: dict) -> dict:
        if not self.is_interactive():
            return self._non_interactive_response(reason, question_type)

        if question_type == "approve":
            return self._ask_approval(reason, context)
        elif question_type == "select":
            return self._ask_selection(reason, context)
        elif question_type == "input":
            return self._ask_free_text(reason, context)
        else:
            return self._ask_approval(reason, context)

    def _ask_approval(self, reason: str, context: dict) -> dict:
        """Binary yes/no approval question."""
        options = context.get("options", ["approve", "deny", "skip"])
        hints = {
            "approve": "Allow this action to proceed",
            "deny":    "Block this action",
            "skip":    "Skip guardrail for this item only (log reason)"
        }

        print("\n  Options:")
        for i, opt in enumerate(options, 1):
            print(f"    [{i}] {opt.upper()} — {hints.get(opt, opt)}")

        while True:
            try:
                answer = input("\n  Your choice (or 'q' to quit all): ").strip().lower()
                if answer == "q":
                    print("  Aborting all escalations.")
                    sys.exit(1)
                if answer.isdigit() and 1 <= int(answer) <= len(options):
                    chosen = options[int(answer) - 1]
                elif answer in options:
                    chosen = answer
                else:
                    print(f"  Invalid choice. Enter 1-{len(options)} or option name.")
                    continue

                reason_text = ""
                if chosen in ("deny", "skip"):
                    reason_text = input("  Reason (optional): ").strip()

                return {
                    "approved": chosen == "approve",
                    "choice": chosen,
                    "reason": reason_text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "responder": "human-cli"
                }
            except (EOFError, KeyboardInterrupt):
                print("\n  Input interrupted. Denying by default.")
                return self._non_interactive_response(reason, "approve")

    def _ask_selection(self, reason: str, context: dict) -> dict:
        """Multiple-choice selection."""
        choices = context.get("choices", [])
        if not choices:
            return self._ask_approval(reason, context)

        print("\n  Select an option:")
        for i, choice in enumerate(choices, 1):
            label = choice if isinstance(choice, str) else choice.get("label", str(choice))
            desc = "" if isinstance(choice, str) else choice.get("description", "")
            print(f"    [{i}] {label}" + (f" — {desc}" if desc else ""))

        while True:
            try:
                answer = input(f"\n  Enter choice (1-{len(choices)}): ").strip()
                if answer.isdigit() and 1 <= int(answer) <= len(choices):
                    chosen = choices[int(answer) - 1]
                    label = chosen if isinstance(chosen, str) else chosen.get("label")
                    return {
                        "approved": True,
                        "selected": label,
                        "choice": label,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "responder": "human-cli"
                    }
                print(f"  Enter a number between 1 and {len(choices)}.")
            except (EOFError, KeyboardInterrupt):
                return self._non_interactive_response(reason, "select")

    def _ask_free_text(self, reason: str, context: dict) -> dict:
        """Open-ended text input."""
        prompt = context.get("prompt", "Please provide input")
        print(f"\n  {prompt}")
        try:
            text = input("  > ").strip()
            return {
                "approved": True,
                "input": text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "responder": "human-cli"
            }
        except (EOFError, KeyboardInterrupt):
            return self._non_interactive_response(reason, "input")

    def _non_interactive_response(self, reason: str, question_type: str) -> dict:
        """Default response when no human is available."""
        approved = self.non_interactive_default == "approve"
        return {
            "approved": approved,
            "choice": self.non_interactive_default,
            "reason": "Non-interactive mode: using default policy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "responder": "auto-policy"
        }

    def _log_decision(self, escalation: dict, response: dict):
        """Append decision to audit log."""
        entry = {
            "id": str(uuid.uuid4()),
            "escalation": escalation,
            "response": response,
            "logged_at": datetime.now(timezone.utc).isoformat()
        }
        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def _send_notification(self, escalation: dict, response: dict):
        """Send notification via webhook."""
        payload = {
            "escalation_reason": escalation.get("reason"),
            "decision": response.get("choice"),
            "approved": response.get("approved"),
            "timestamp": response.get("timestamp"),
            "responder": response.get("responder")
        }

        # Generic webhook
        if self.webhook_url:
            self._post_json(self.webhook_url, payload)

        # Slack-formatted message
        if self.slack_webhook:
            icon = ":white_check_mark:" if response.get("approved") else ":x:"
            slack_payload = {
                "text": f"{icon} *Guardrails Escalation Decision*",
                "attachments": [{
                    "color": "good" if response.get("approved") else "danger",
                    "fields": [
                        {"title": "Reason",   "value": escalation.get("reason", "-"), "short": False},
                        {"title": "Decision", "value": response.get("choice", "-"),   "short": True},
                        {"title": "By",       "value": response.get("responder", "-"),"short": True},
                    ]
                }]
            }
            self._post_json(self.slack_webhook, slack_payload)

    def _post_json(self, url: str, payload: dict):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # Notifications are best-effort

    def create_approval_request(self, escalation: dict) -> dict:
        """
        Create a structured approval request (for async/API-based workflows).
        Returns a request object that can be serialized and sent to an approval system.
        """
        return {
            "id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": datetime.fromtimestamp(
                time.time() + self.approval_timeout_secs, tz=timezone.utc
            ).isoformat(),
            "reason": escalation.get("reason"),
            "context": escalation.get("context", {}),
            "status": "pending",
            "required_approvers": 1,
            "approvals": []
        }
