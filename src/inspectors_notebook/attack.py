"""MITRE ATT&CK Enterprise tactics, for the analyst's tags on events. Tags are never guessed.

Tags store the tactic ID, which MITRE keeps stable; names are shown as of VERSION. v20 split
Defense Evasion into Stealth (TA0005, the old ID) and Defense Impairment (TA0112).
Source: https://attack.mitre.org/tactics/enterprise/
"""

VERSION = "v20"  # of ATT&CK

TACTICS = {  # in the matrix's order
    "TA0043": "Reconnaissance",
    "TA0042": "Resource Development",
    "TA0001": "Initial Access",
    "TA0002": "Execution",
    "TA0003": "Persistence",
    "TA0004": "Privilege Escalation",
    "TA0005": "Stealth",
    "TA0112": "Defense Impairment",
    "TA0006": "Credential Access",
    "TA0007": "Discovery",
    "TA0008": "Lateral Movement",
    "TA0009": "Collection",
    "TA0011": "Command and Control",
    "TA0010": "Exfiltration",
    "TA0040": "Impact",
}


def clean(ids) -> list[str]:
    """Known tactic IDs, once each, in the matrix's order; anything else is dropped."""
    chosen = {str(i) for i in ids} if isinstance(ids, (list, tuple)) else set()
    return [t for t in TACTICS if t in chosen]


def label(tactic_id: str) -> str:
    return f"{TACTICS[tactic_id]} ({tactic_id})"
