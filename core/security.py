"""
Security Utilities for LLM Applications
=======================================

Protects against prompt injection, input manipulation, and data exfiltration.

Why this is crucial:
1. User/external data in prompts can override system instructions
2. Malicious inputs can extract sensitive information
3. Unvalidated URLs can inject harmful content
4. LLM outputs may contain malicious content

Usage:
    from core.security import (
        sanitize_for_prompt,
        validate_url,
        validate_company_name,
        detect_prompt_injection,
        escape_markdown,
    )

    # Sanitize before inserting into prompt
    safe_name = sanitize_for_prompt(company_name)
    prompt = f"Generate briefing for {safe_name}"

    # Validate URL before processing
    if not validate_url(user_url):
        raise ValueError("Invalid URL")

    # Check for injection attempts
    if detect_prompt_injection(user_input):
        logger.warning("Potential prompt injection detected")
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# =============================================================================
# PROMPT INJECTION DETECTION
# =============================================================================

# Patterns that indicate prompt injection attempts
INJECTION_PATTERNS = [
    # Instruction override attempts
    r"ignore\s+(previous|above|all)\s+(instructions?|prompts?|rules?)",
    r"disregard\s+(previous|above|all)\s+(instructions?|prompts?|rules?)",
    r"forget\s+(previous|above|all)\s+(instructions?|prompts?|rules?)",
    r"override\s+(system|previous)\s+(prompt|instructions?)",
    r"new\s+instructions?:",
    r"system\s*:\s*you\s+are",
    r"<\s*system\s*>",
    r"\[\s*system\s*\]",

    # Role manipulation
    r"you\s+are\s+now\s+a",
    r"act\s+as\s+if\s+you\s+are",
    r"pretend\s+(to\s+be|you\s+are)",
    r"roleplay\s+as",
    r"from\s+now\s+on\s+you",

    # Data exfiltration attempts
    r"(reveal|show|display|print|output)\s+(your|the)\s+(system|initial|original)\s+(prompt|instructions?)",
    r"what\s+(are|were)\s+your\s+(original|initial|system)\s+(instructions?|prompts?)",
    r"repeat\s+(your|the)\s+(system|initial)\s+(prompt|instructions?)",

    # Delimiter escape attempts
    r"```\s*(system|instruction|prompt)",
    r"<\/?(system|instruction|prompt|assistant|user)>",

    # Jailbreak patterns
    r"do\s+anything\s+now",
    r"dan\s+mode",
    r"developer\s+mode",
    r"(enable|activate)\s+.*mode",
    r"bypass\s+(safety|content|filter)",
]

# Compiled patterns for efficiency
_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


@dataclass
class InjectionDetectionResult:
    """Result of prompt injection detection."""
    is_suspicious: bool
    confidence: float  # 0.0 to 1.0
    matched_patterns: list[str]
    sanitized_input: str


def detect_prompt_injection(
    text: str,
    threshold: float = 0.3,
) -> InjectionDetectionResult:
    """
    Detect potential prompt injection attempts in text.

    Args:
        text: Text to analyze
        threshold: Confidence threshold for flagging (0.0-1.0)

    Returns:
        InjectionDetectionResult with detection details

    Note: This is a heuristic-based detection. It may have false positives/negatives.
    Use as one layer of defense, not the only protection.
    """
    if not text:
        return InjectionDetectionResult(
            is_suspicious=False,
            confidence=0.0,
            matched_patterns=[],
            sanitized_input="",
        )

    text_lower = text.lower()
    matched_patterns = []

    for pattern in _COMPILED_PATTERNS:
        if pattern.search(text_lower):
            matched_patterns.append(pattern.pattern)

    # Calculate confidence based on number of matches
    if matched_patterns:
        # More matches = higher confidence
        confidence = min(1.0, len(matched_patterns) * 0.3)
    else:
        confidence = 0.0

    is_suspicious = confidence >= threshold

    if is_suspicious:
        logger.warning(
            f"Potential prompt injection detected (confidence: {confidence:.2f}). "
            f"Matched patterns: {matched_patterns[:3]}"
        )

    return InjectionDetectionResult(
        is_suspicious=is_suspicious,
        confidence=confidence,
        matched_patterns=matched_patterns,
        sanitized_input=sanitize_for_prompt(text) if is_suspicious else text,
    )


# =============================================================================
# INPUT SANITIZATION
# =============================================================================

# Maximum lengths for different input types
MAX_COMPANY_NAME_LENGTH = 200
MAX_URL_LENGTH = 2000
MAX_CONTENT_LENGTH = 50000  # For news excerpts, backgrounds, etc.

# Characters that could be used for prompt manipulation
DANGEROUS_SEQUENCES = [
    "```",           # Code block markers
    "---",           # Horizontal rules
    "***",           # Bold/italic
    "<<<",           # Potential delimiters
    ">>>",
    "[[",            # Wiki-style links
    "]]",
    "{{",            # Template syntax
    "}}",
    "<|",            # Common LLM special tokens
    "|>",
    "[INST]",        # Instruction markers
    "[/INST]",
    "<s>",           # Sentence markers
    "</s>",
]


def sanitize_for_prompt(
    text: str,
    max_length: int = MAX_CONTENT_LENGTH,
    escape_markdown: bool = True,
    remove_dangerous: bool = True,
) -> str:
    """
    Sanitize text before inserting into an LLM prompt.

    This helps prevent prompt injection by:
    1. Limiting length to prevent token exhaustion
    2. Escaping markdown that could create false structure
    3. Removing potentially dangerous sequences

    Args:
        text: Text to sanitize
        max_length: Maximum allowed length
        escape_markdown: Whether to escape markdown characters
        remove_dangerous: Whether to remove dangerous sequences

    Returns:
        Sanitized text safe for prompt insertion
    """
    if not text:
        return ""

    # Strip and limit length
    text = text.strip()
    if len(text) > max_length:
        text = text[:max_length] + "..."
        logger.debug(f"Truncated text to {max_length} characters")

    # Remove dangerous sequences
    if remove_dangerous:
        for seq in DANGEROUS_SEQUENCES:
            text = text.replace(seq, " ")

    # Escape markdown if requested
    if escape_markdown:
        text = escape_markdown_chars(text)

    # Remove null bytes and other control characters
    text = "".join(char for char in text if ord(char) >= 32 or char in "\n\t")

    return text


def escape_markdown_chars(text: str) -> str:
    """
    Escape markdown special characters to prevent formatting injection.

    Args:
        text: Text to escape

    Returns:
        Text with markdown characters escaped
    """
    # Characters that affect markdown rendering
    markdown_chars = ["*", "_", "`", "#", "[", "]", "(", ")", "<", ">", "!", "|"]

    for char in markdown_chars:
        text = text.replace(char, "\\" + char)

    return text


def sanitize_company_name(name: str) -> str:
    """
    Sanitize a company name for safe use in prompts.

    Args:
        name: Company name to sanitize

    Returns:
        Sanitized company name
    """
    if not name:
        return "Unknown Company"

    # Basic sanitization
    name = name.strip()

    # Limit length
    if len(name) > MAX_COMPANY_NAME_LENGTH:
        name = name[:MAX_COMPANY_NAME_LENGTH]

    # Remove dangerous sequences
    for seq in DANGEROUS_SEQUENCES:
        name = name.replace(seq, "")

    # Remove control characters but keep basic punctuation
    name = "".join(
        char for char in name
        if char.isalnum() or char in " .,&'-()/"
    )

    # Collapse multiple spaces
    name = " ".join(name.split())

    if not name:
        return "Unknown Company"

    return name


def wrap_user_content(content: str, label: str = "USER_DATA") -> str:
    """
    Wrap user content in clear delimiters to separate from instructions.

    This helps the LLM distinguish between instructions and data.

    Args:
        content: User/external content
        label: Label for the content block

    Returns:
        Content wrapped with clear delimiters
    """
    sanitized = sanitize_for_prompt(content)
    return f"\n<{label}>\n{sanitized}\n</{label}>\n"


# =============================================================================
# URL VALIDATION
# =============================================================================

# Allowed URL schemes
ALLOWED_SCHEMES = {"http", "https"}

# Blocked domains (example list - extend as needed)
BLOCKED_DOMAINS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",  # AWS metadata
    "metadata.google.internal",  # GCP metadata
}

# Blocked TLDs that are often malicious
BLOCKED_TLDS = {
    "onion",  # Tor
    "local",
}


@dataclass
class URLValidationResult:
    """Result of URL validation."""
    is_valid: bool
    domain: Optional[str]
    error: Optional[str]
    normalized_url: Optional[str]


def validate_url(
    url: str,
    require_https: bool = False,
    max_length: int = MAX_URL_LENGTH,
) -> URLValidationResult:
    """
    Validate and normalize a URL for safe processing.

    Args:
        url: URL to validate
        require_https: Whether to require HTTPS
        max_length: Maximum URL length

    Returns:
        URLValidationResult with validation details
    """
    if not url:
        return URLValidationResult(
            is_valid=False,
            domain=None,
            error="URL is empty",
            normalized_url=None,
        )

    url = url.strip()

    # Check length
    if len(url) > max_length:
        return URLValidationResult(
            is_valid=False,
            domain=None,
            error=f"URL exceeds maximum length of {max_length}",
            normalized_url=None,
        )

    # Check for non-http schemes BEFORE adding https prefix
    # This prevents ftp://example.com from becoming https://ftp://example.com
    if "://" in url:
        scheme = url.split("://")[0].lower()
        if scheme not in ALLOWED_SCHEMES:
            return URLValidationResult(
                is_valid=False,
                domain=None,
                error=f"Invalid scheme: {scheme}. Must be http or https.",
                normalized_url=None,
            )

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        return URLValidationResult(
            is_valid=False,
            domain=None,
            error=f"Invalid URL format: {e}",
            normalized_url=None,
        )

    # Check scheme (redundant but safe)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return URLValidationResult(
            is_valid=False,
            domain=None,
            error=f"Invalid scheme: {parsed.scheme}. Must be http or https.",
            normalized_url=None,
        )

    if require_https and parsed.scheme != "https":
        return URLValidationResult(
            is_valid=False,
            domain=None,
            error="HTTPS required",
            normalized_url=None,
        )

    # Extract and validate domain
    domain = parsed.netloc.lower()
    if not domain:
        return URLValidationResult(
            is_valid=False,
            domain=None,
            error="No domain in URL",
            normalized_url=None,
        )

    # Remove port if present for domain checking
    domain_without_port = domain.split(":")[0]

    # Check blocked domains
    if domain_without_port in BLOCKED_DOMAINS:
        return URLValidationResult(
            is_valid=False,
            domain=domain,
            error=f"Blocked domain: {domain_without_port}",
            normalized_url=None,
        )

    # Check blocked TLDs
    tld = domain_without_port.split(".")[-1] if "." in domain_without_port else ""
    if tld in BLOCKED_TLDS:
        return URLValidationResult(
            is_valid=False,
            domain=domain,
            error=f"Blocked TLD: {tld}",
            normalized_url=None,
        )

    # Check for IP addresses in domain (potential SSRF)
    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", domain_without_port):
        return URLValidationResult(
            is_valid=False,
            domain=domain,
            error="IP addresses not allowed in URLs",
            normalized_url=None,
        )

    # Normalize URL
    normalized = f"{parsed.scheme}://{domain}{parsed.path}"
    if parsed.query:
        normalized += f"?{parsed.query}"

    return URLValidationResult(
        is_valid=True,
        domain=domain,
        error=None,
        normalized_url=normalized,
    )


def validate_company_name(name: str) -> tuple[bool, str, Optional[str]]:
    """
    Validate a company name for safe processing.

    Args:
        name: Company name to validate

    Returns:
        Tuple of (is_valid, sanitized_name, error_message)
    """
    if not name:
        return False, "", "Company name is empty"

    name = name.strip()

    # Check length
    if len(name) > MAX_COMPANY_NAME_LENGTH:
        return False, "", f"Company name exceeds maximum length of {MAX_COMPANY_NAME_LENGTH}"

    # Check for injection patterns
    detection = detect_prompt_injection(name)
    if detection.is_suspicious:
        logger.warning(f"Suspicious company name detected: {name[:50]}...")
        return False, "", "Company name contains suspicious patterns"

    # Sanitize and return
    sanitized = sanitize_company_name(name)

    if not sanitized or sanitized == "Unknown Company":
        return False, "", "Company name is invalid after sanitization"

    return True, sanitized, None


# =============================================================================
# OUTPUT SANITIZATION
# =============================================================================

def sanitize_llm_output_for_display(output: str) -> str:
    """
    Sanitize LLM output before displaying to users.

    This prevents XSS if output is rendered in HTML context.

    Args:
        output: Raw LLM output

    Returns:
        Sanitized output safe for display
    """
    if not output:
        return ""

    # Escape HTML entities
    output = html.escape(output)

    return output


def sanitize_url_for_markdown(url: str) -> Optional[str]:
    """
    Sanitize a URL before inserting into markdown link.

    Args:
        url: URL to sanitize

    Returns:
        Sanitized URL or None if invalid
    """
    validation = validate_url(url)
    if not validation.is_valid:
        logger.warning(f"Invalid URL rejected: {validation.error}")
        return None

    # Additional escaping for markdown
    safe_url = validation.normalized_url
    safe_url = safe_url.replace(")", "%29")  # Escape closing paren
    safe_url = safe_url.replace("(", "%28")  # Escape opening paren

    return safe_url


# =============================================================================
# SECURE PROMPT CONSTRUCTION
# =============================================================================

def build_secure_prompt(
    template: str,
    user_data: dict[str, str],
    system_context: Optional[dict[str, str]] = None,
) -> str:
    """
    Build a prompt with proper separation between instructions and user data.

    Args:
        template: Prompt template with {placeholders}
        user_data: Dictionary of user-provided data (will be sanitized)
        system_context: Dictionary of system-provided context (trusted)

    Returns:
        Safely constructed prompt

    Example:
        prompt = build_secure_prompt(
            template="Analyze the company: {company_name}\n\nData:\n{company_data}",
            user_data={
                "company_name": user_input_name,
                "company_data": external_api_data,
            },
        )
    """
    # Sanitize all user data
    sanitized_data = {}
    for key, value in user_data.items():
        # Check for injection
        detection = detect_prompt_injection(value)
        if detection.is_suspicious:
            logger.warning(f"Injection attempt in {key}: using sanitized version")
            sanitized_data[key] = detection.sanitized_input
        else:
            sanitized_data[key] = sanitize_for_prompt(value)

    # Merge with system context (trusted, no sanitization needed)
    all_data = {}
    if system_context:
        all_data.update(system_context)
    all_data.update(sanitized_data)

    # Build prompt
    try:
        return template.format(**all_data)
    except KeyError as e:
        raise ValueError(f"Missing placeholder in template: {e}")


# =============================================================================
# SECURITY AUDIT LOGGING
# =============================================================================

def log_security_event(
    event_type: str,
    details: dict,
    severity: str = "warning",
) -> None:
    """
    Log a security-relevant event.

    Args:
        event_type: Type of security event
        details: Event details
        severity: Log severity (info, warning, error)
    """
    message = f"SECURITY_EVENT: {event_type} | {details}"

    if severity == "error":
        logger.error(message)
    elif severity == "warning":
        logger.warning(message)
    else:
        logger.info(message)
