"""
extraction/diarizer.py
----------------------
Takes clean transcript text and segments it into blocks by speaker.
Identifies the speaker's role (CEO, CFO, Analyst, etc.) and filters to keep only
target executives based on predefined roles in config.py.

Usage:
    statements = diarize_transcript(text, company_id)
    # returns list of dicts: [{'speaker': '...', 'role': '...', 'text': '...', 'executive_id': int}]
"""

import re
from loguru import logger
from storage.database import upsert_executive
from config import EXECUTIVE_ROLES

# Pattern captures "First Last:" or "First Last (Role):"
# Looks for capitalised names followed by colon or parenthesis.
# It uses positive lookahead (?=\n[A-Z]|\Z) to capture everything until the next speaker.
SPEAKER_PATTERN = re.compile(
    r'\n?([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s*(?:[-–]*\s*([^:\n]*))?:\s*(.*?)(?=\n[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\s*(?:[-–]*\s*[^:\n]*)?:|\Z)',
    re.DOTALL
)

# Alternative pattern for transcripts formatted as: "Rajesh Kumar (CFO): text..."
SPEAKER_PATTERN_ALT = re.compile(
    r'\n?([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s*(?:\(([^)]+)\))?:\s*(.*?)(?=\n[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\s*(?:\([^)]+\))?:|\Z)',
    re.DOTALL
)

def _detect_role(speaker_name: str, explicit_role: str, full_text: str) -> str:
    """
    Determine the role of the speaker.
    1. Check if role was explicitly captured in the regex (e.g. "Rajesh Kumar - CFO:").
    2. Fallback: Search the entire transcript text for context like "Mr. Rajesh Kumar, CFO" or "Managing Director, Rajesh Kumar".
    """
    explicit_role = (explicit_role or "").strip()
    if explicit_role:
        return explicit_role

    # Check for Analyst vs Management generically
    if "analyst" in speaker_name.lower():
        return "Analyst"
    if "moderator" in speaker_name.lower() or "operator" in speaker_name.lower():
        return "Moderator"

    # Search context near the first mention of the name in the text
    # e.g., "We have with us Mr. John Doe, Chief Financial Officer"
    name_parts = speaker_name.split()
    if len(name_parts) >= 2:
        last_name = name_parts[-1]
        # Look for a 100 char window around the name
        match = re.search(f"{last_name}.{{0,100}}?(CFO|CEO|MD|Chief Financial|Chief Executive|Managing Director)", full_text, re.IGNORECASE | re.DOTALL)
        if match:
            role = match.group(1).upper()
            if "FINANCIAL" in role: return "CFO"
            if "EXECUTIVE" in role: return "CEO"
            if "MANAGING" in role: return "MD"
            return role
            
        match_before = re.search(f"(CFO|CEO|MD|Chief Financial|Chief Executive|Managing Director).{{0,100}}?{last_name}", full_text, re.IGNORECASE | re.DOTALL)
        if match_before:
            role = match_before.group(1).upper()
            if "FINANCIAL" in role: return "CFO"
            if "EXECUTIVE" in role: return "CEO"
            if "MANAGING" in role: return "MD"
            return role

    return "Unknown"


def is_target_executive(role: str) -> bool:
    role_upper = role.upper()
    return any(target_role.upper() in role_upper for target_role in EXECUTIVE_ROLES)


def diarize_transcript(text: str, company_id: int) -> list[dict]:
    """
    Parse transcript, identify speakers, filter for executives, and upsert them to the DB.
    """
    statements = []
    
    # Try alternate pattern first (with parentheses) as it's more specific, then standard
    matches = list(SPEAKER_PATTERN_ALT.finditer(text))
    if not matches or len(matches) < 5:
        matches = list(SPEAKER_PATTERN.finditer(text))

    logger.debug(f"  [Diarizer] Found {len(matches)} speaker turns")

    executives_cache = {}

    for match in matches:
        speaker_name = match.group(1).strip()
        explicit_role = match.group(2)
        content = match.group(3).strip()

        # Skip very short blocks or empty names
        if len(content) < 10 or not speaker_name:
            continue
            
        # Ignore obvious non-human speakers that regex might have grabbed
        if speaker_name.upper() == speaker_name or len(speaker_name.split()) > 4:
             continue

        role = _detect_role(speaker_name, explicit_role, text)

        if is_target_executive(role):
            # Upsert to database and get ID
            if speaker_name not in executives_cache:
                exec_id = upsert_executive(
                    name=speaker_name,
                    role=role,
                    company_id=company_id
                )
                executives_cache[speaker_name] = exec_id
            
            executive_id = executives_cache[speaker_name]

            statements.append({
                "speaker": speaker_name,
                "role": role,
                "text": content,
                "executive_id": executive_id
            })

    return statements
