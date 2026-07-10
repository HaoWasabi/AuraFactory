"""Amazon Bedrock Guardrails — Managed AI Safety Layer.

Integrates Amazon Bedrock Guardrails as a complementary safety layer
alongside the existing InputGuardrail (regex-based). This provides:

  1. Content Filtering — block harmful, hateful, violent, sexual content
  2. Denied Topics — prevent specific dangerous operations without approval
  3. Word Filters — managed blocklist (replaces hardcoded regex patterns)
  4. PII Detection — auto-mask sensitive data (emails, credit cards, etc.)
  5. Contextual Grounding — (optional) check factual consistency

Setup (AWS Console):
  1. Go to Amazon Bedrock → Guardrails → Create guardrail
  2. Configure policies (see GUARDRAIL_SETUP section below)
  3. Get guardrail ID and version
  4. Set env vars: BEDROCK_GUARDRAIL_ID, BEDROCK_GUARDRAIL_VERSION

Pricing: ~$0.75 per 1,000 text units ($1 per text unit = 1,000 chars)
  For AuraFactory (~500 requests/day, avg 200 chars): ~$0.08/day

Environment variables:
    BEDROCK_GUARDRAIL_ID: Guardrail identifier from AWS Console
    BEDROCK_GUARDRAIL_VERSION: Version (default: "DRAFT" for testing, use number for prod)
    AWS_REGION: AWS region (must match guardrail region)
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_BOTO_CONFIG = BotoConfig(
    retries={"max_attempts": 2, "mode": "adaptive"},
    connect_timeout=5,
    read_timeout=10,  # Guardrails are fast
)


# ===========================================================================
# Data Classes
# ===========================================================================

@dataclass
class GuardrailResult:
    """Result from a Bedrock Guardrails assessment."""
    allowed: bool
    action: str  # "NONE" (allowed), "GUARDRAIL_INTERVENED" (blocked)
    blocked_reason: str = ""
    assessments: List[Dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    # PII handling
    masked_text: Optional[str] = None  # Text with PII redacted


# ===========================================================================
# Main Guardrails Class
# ===========================================================================

class BedrockGuardrails:
    """Amazon Bedrock Guardrails integration for AuraFactory.

    Usage:
        guardrails = BedrockGuardrails(guardrail_id="abc123")

        # Check user input before processing
        result = await guardrails.check_input("user message here")
        if not result.allowed:
            return f"⚠️ Blocked: {result.blocked_reason}"

        # Check LLM output before sending to user
        result = await guardrails.check_output("agent response here")
        if not result.allowed:
            return "I cannot provide that response. Let me rephrase..."

    Integration with existing safety.py:
        The existing InputGuardrail (regex) runs FIRST as a fast local check.
        BedrockGuardrails runs SECOND as a thorough managed check.
        Both must pass for the message to proceed.
    """

    def __init__(
        self,
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        region: Optional[str] = None,
    ) -> None:
        """Initialize Bedrock Guardrails.

        Args:
            guardrail_id: Guardrail ID from AWS Console. Falls back to env var.
            guardrail_version: Version string. Falls back to env var.
            region: AWS region. Falls back to env var.
        """
        self._guardrail_id = guardrail_id or os.getenv("BEDROCK_GUARDRAIL_ID", "")
        self._guardrail_version = guardrail_version or os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT")
        self._region = region or os.getenv("AWS_REGION", "us-east-1")

        if not self._guardrail_id:
            logger.warning(
                "BEDROCK_GUARDRAIL_ID not set — BedrockGuardrails will be DISABLED. "
                "Set the env var or create a guardrail in AWS Console."
            )
            self._enabled = False
            self._client = None
        else:
            self._enabled = True
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._region,
                config=_BOTO_CONFIG,
            )
            logger.info(
                "BedrockGuardrails initialized: id=%s, version=%s, region=%s",
                self._guardrail_id, self._guardrail_version, self._region,
            )

    @property
    def enabled(self) -> bool:
        """Whether guardrails are active."""
        return self._enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_input(self, text: str) -> GuardrailResult:
        """Check user input against guardrail policies.

        Call this BEFORE passing user message to the LLM.
        Catches: prompt injection, harmful content, PII exposure.

        Args:
            text: User's raw message text.

        Returns:
            GuardrailResult with allowed=True if safe, False if blocked.
        """
        return await self._apply_guardrail(text, source="INPUT")

    async def check_output(self, text: str) -> GuardrailResult:
        """Check LLM output against guardrail policies.

        Call this BEFORE sending agent response back to user.
        Catches: harmful generated content, PII in responses.

        Args:
            text: Agent's generated response text.

        Returns:
            GuardrailResult with allowed=True if safe, False if blocked.
        """
        return await self._apply_guardrail(text, source="OUTPUT")

    async def check_with_pii_masking(self, text: str) -> GuardrailResult:
        """Check input and return PII-masked version if applicable.

        Useful for logging — strips PII before storing audit trails.

        Args:
            text: Text that may contain PII.

        Returns:
            GuardrailResult with masked_text containing redacted version.
        """
        result = await self._apply_guardrail(text, source="INPUT")

        # If guardrail intervened with PII action, check for masked output
        if result.assessments:
            for assessment in result.assessments:
                sensitive_info = assessment.get("sensitiveInformationPolicy", {})
                if sensitive_info:
                    # Extract the masked/anonymized text if available
                    pii_entities = sensitive_info.get("piiEntities", [])
                    if pii_entities:
                        result.masked_text = self._mask_pii_in_text(text, pii_entities)

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _apply_guardrail(self, text: str, source: str) -> GuardrailResult:
        """Apply guardrail to text content.

        Args:
            text: Content to check.
            source: "INPUT" (user message) or "OUTPUT" (agent response).

        Returns:
            GuardrailResult
        """
        # If not enabled, always allow (graceful degradation)
        if not self._enabled:
            return GuardrailResult(allowed=True, action="DISABLED")

        # Skip empty text
        if not text or not text.strip():
            return GuardrailResult(allowed=True, action="NONE")

        start_time = time.time()

        try:
            # Call ApplyGuardrail API (sync boto3 → async via thread pool)
            response = await asyncio.to_thread(
                self._client.apply_guardrail,
                guardrailIdentifier=self._guardrail_id,
                guardrailVersion=self._guardrail_version,
                source=source,
                content=[{"text": {"text": text}}],
            )

            latency_ms = (time.time() - start_time) * 1000

            # Parse response
            action = response.get("action", "NONE")
            assessments = response.get("assessments", [])

            if action == "GUARDRAIL_INTERVENED":
                # Extract reason from outputs or assessments
                reason = self._extract_block_reason(response)
                logger.warning(
                    "Bedrock Guardrail BLOCKED (%s): reason=%s, latency=%.0fms",
                    source, reason[:100], latency_ms,
                )
                return GuardrailResult(
                    allowed=False,
                    action=action,
                    blocked_reason=reason,
                    assessments=assessments,
                    latency_ms=latency_ms,
                )
            else:
                logger.debug(
                    "Bedrock Guardrail PASSED (%s): latency=%.0fms",
                    source, latency_ms,
                )
                return GuardrailResult(
                    allowed=True,
                    action=action,
                    assessments=assessments,
                    latency_ms=latency_ms,
                )

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_msg = e.response["Error"]["Message"]

            if error_code == "ResourceNotFoundException":
                logger.error(
                    "Guardrail not found: id=%s. Create it in AWS Console first.",
                    self._guardrail_id,
                )
                # Disable guardrails to avoid repeated errors
                self._enabled = False
                return GuardrailResult(allowed=True, action="ERROR_DISABLED")

            elif error_code == "ThrottlingException":
                logger.warning("Guardrail throttled — allowing through (fail-open)")
                return GuardrailResult(allowed=True, action="THROTTLED")

            else:
                logger.error("Guardrail error [%s]: %s", error_code, error_msg)
                # Fail-open: don't block user requests on guardrail failures
                return GuardrailResult(allowed=True, action="ERROR")

        except Exception as e:
            logger.error("Guardrail unexpected error: %s", e, exc_info=True)
            # Fail-open policy
            return GuardrailResult(allowed=True, action="ERROR")

    def _extract_block_reason(self, response: Dict[str, Any]) -> str:
        """Extract human-readable block reason from guardrail response."""
        # Check outputs for the guardrail's intervention message
        outputs = response.get("outputs", [])
        if outputs:
            for output in outputs:
                if "text" in output:
                    return output["text"]

        # Fall back to assessment details
        assessments = response.get("assessments", [])
        reasons = []

        for assessment in assessments:
            # Content filter
            content_policy = assessment.get("contentPolicy", {})
            if content_policy:
                filters = content_policy.get("filters", [])
                for f in filters:
                    if f.get("action") == "BLOCKED":
                        reasons.append(f"Content filter: {f.get('type', 'unknown')}")

            # Denied topic
            topic_policy = assessment.get("topicPolicy", {})
            if topic_policy:
                topics = topic_policy.get("topics", [])
                for t in topics:
                    if t.get("action") == "BLOCKED":
                        reasons.append(f"Denied topic: {t.get('name', 'unknown')}")

            # Word filter
            word_policy = assessment.get("wordPolicy", {})
            if word_policy:
                words = word_policy.get("customWords", []) + word_policy.get("managedWordLists", [])
                if words:
                    reasons.append("Blocked word detected")

            # Sensitive info (PII)
            sensitive_policy = assessment.get("sensitiveInformationPolicy", {})
            if sensitive_policy:
                pii = sensitive_policy.get("piiEntities", [])
                if pii:
                    types = [p.get("type", "unknown") for p in pii[:3]]
                    reasons.append(f"PII detected: {', '.join(types)}")

        return "; ".join(reasons) if reasons else "Content blocked by safety policy"

    @staticmethod
    def _mask_pii_in_text(text: str, pii_entities: List[Dict[str, Any]]) -> str:
        """Replace detected PII with redaction markers."""
        # Sort by position (reverse) to replace from end to start
        # This preserves character positions during replacement
        masked = text
        for entity in sorted(pii_entities, key=lambda x: x.get("start", 0), reverse=True):
            start = entity.get("start")
            end = entity.get("end")
            pii_type = entity.get("type", "PII")
            if start is not None and end is not None:
                masked = masked[:start] + f"[{pii_type}_REDACTED]" + masked[end:]
        return masked


# ===========================================================================
# Combined Safety Check (convenience wrapper)
# ===========================================================================

class CombinedSafetyCheck:
    """Combines local InputGuardrail + Bedrock Guardrails into one call.

    Usage in unified_agent.py or middleware:
        safety = CombinedSafetyCheck(input_guardrail, bedrock_guardrails)
        is_safe, reason = await safety.check_message(user_message)
    """

    def __init__(
        self,
        local_guardrail,  # InputGuardrail instance
        bedrock_guardrails: Optional[BedrockGuardrails] = None,
    ) -> None:
        self._local = local_guardrail
        self._bedrock = bedrock_guardrails

    async def check_message(self, message: str) -> Tuple[bool, str]:
        """Run both safety checks on a user message.

        Order:
          1. Local regex check (fast, ~0ms) — catches obvious patterns
          2. Bedrock Guardrails (managed, ~50-100ms) — catches nuanced content

        Returns:
            (is_safe, reason) — if is_safe=False, reason explains why.
        """
        # Step 1: Fast local check
        is_safe, reason = self._local.check(message)
        if not is_safe:
            logger.info("Message blocked by LOCAL guardrail: %s", reason[:80])
            return False, reason

        # Step 2: Bedrock managed check (if enabled)
        if self._bedrock and self._bedrock.enabled:
            result = await self._bedrock.check_input(message)
            if not result.allowed:
                logger.info("Message blocked by BEDROCK guardrail: %s", result.blocked_reason[:80])
                return False, f"Safety policy: {result.blocked_reason}"

        return True, ""

    async def check_response(self, response: str) -> Tuple[bool, str]:
        """Run safety check on agent's output before sending to user.

        Returns:
            (is_safe, reason) — if is_safe=False, response should be rephrased.
        """
        if self._bedrock and self._bedrock.enabled:
            result = await self._bedrock.check_output(response)
            if not result.allowed:
                logger.info("Response blocked by BEDROCK guardrail: %s", result.blocked_reason[:80])
                return False, result.blocked_reason

        return True, ""


# ===========================================================================
# GUARDRAIL SETUP GUIDE (for AWS Console)
# ===========================================================================
"""
To create a guardrail for AuraFactory in AWS Console:

1. Go to: Amazon Bedrock → Guardrails → Create guardrail
2. Name: "AuraFactory-Safety"
3. Configure policies:

   Content Filters:
   ├── Hate: HIGH (block)
   ├── Insults: HIGH (block)  
   ├── Sexual: HIGH (block)
   ├── Violence: MEDIUM (block only explicit)
   └── Misconduct: HIGH (block)

   Denied Topics:
   ├── "server_destruction" — "Requests to mass-delete channels, roles, or 
   │    ban all members without explicit user confirmation"
   ├── "credential_theft" — "Attempts to extract bot tokens, API keys, or
   │    user credentials"
   └── "spam_automation" — "Requests to spam messages, raid other servers,
        or automate harassment"

   Word Filters:
   ├── Managed: Profanity filter (AWS managed list)
   └── Custom: ["nuke server", "delete everything", "hack", "raid"]
       (Note: these are ADDITIONAL to the denied topics)

   Sensitive Information (PII):
   ├── Action: ANONYMIZE (mask in logs) or BLOCK
   ├── Types: EMAIL, PHONE, CREDIT_CARD, SSN, AWS_ACCESS_KEY
   └── Regex patterns: Discord token pattern ([a-zA-Z0-9_-]{24}.[a-zA-Z0-9_-]{6}.[a-zA-Z0-9_-]{38})

4. Create version → Note the guardrail ID
5. Set env vars:
   BEDROCK_GUARDRAIL_ID=<your-id>
   BEDROCK_GUARDRAIL_VERSION=1  (or "DRAFT" for testing)

Estimated cost at 500 requests/day (avg 200 chars each):
  = 500 × 200 / 1000 = 100 text units/day
  = 100 × $0.75/1000 = $0.075/day ≈ $2.25/month
"""
