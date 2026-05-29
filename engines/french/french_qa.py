"""
French QA engine.
Checks: German residue in FR output, Dutch words in FR output.
Never imports from nl_engine.py.
"""

import re

# German words that should never appear in French output
_FR_GERMAN_RESIDUE_RE = re.compile(
    r'\b(?:'
    r'Dekor|Schrank|Tisch|Sofa|Sessel|Leuchte|Lampe|Schublade|Kommode|Bett|Stuhl|'
    r'Regal|Sideboard|Highboard|Spanplatte|Arbeitsplatte|Küche|Kochfeld|'
    r'Hängeschrank|Oberschrank|Unterschrank|Waschtisch|Waschbecken|Badezimmer|'
    r'Spiegel|Füße|Breite|Höhe|Tiefe|Länge|Maße|'
    r'Baumwolle|Polyester|Wolle|Leinen|'
    r'Schwarz|Weiß|Grau|Braun|Blau|Grün|Rot|Anthrazit|Silber|'
    r'teilig|Sitzer|flammig|Typ\b'
    r')\b',
    re.UNICODE,
)

# Dutch words that should never appear in French output
_DUTCH_IN_FRENCH_RE = re.compile(
    r'\b(?:'
    r'zwart|wit|grijs|bruin|blauw|groen|rood|geel|roze|oranje|beige|'
    r'eiken|eikenlook|notenlook|betonlook|marmerlook|'
    r'bank|stoel|tafel|kast|lade|plank|lamp|hanglamp|staande lamp|'
    r'werkblad|kookplaat|kookeiland|afzuigkap|'
    r'inclusief|bestaande uit|set van|'
    r'zwarte|witte|grijze|bruine|blauwe|groene|rode'
    r')\b',
    re.IGNORECASE | re.UNICODE,
)


class FrenchQA:
    """QA checks for French translation output."""

    def check(self, text: str, source: str = "") -> list[dict]:
        """
        Run QA checks on a French translation.
        Returns list of issues: [{severity, category, message}].
        """
        issues = []

        # German residue check
        german_matches = _FR_GERMAN_RESIDUE_RE.findall(text)
        if german_matches:
            issues.append({
                "severity": "High",
                "category": "German residue",
                "message":  f"German words in FR output: {', '.join(sorted(set(german_matches)))}",
            })

        # Dutch contamination check
        dutch_matches = _DUTCH_IN_FRENCH_RE.findall(text)
        if dutch_matches:
            issues.append({
                "severity": "Critical",
                "category": "Language contamination",
                "message":  f"Dutch words in FR output: {', '.join(sorted(set(w.lower() for w in dutch_matches)))}",
            })

        # Residual "Dekor" not localized
        if re.search(r'\bDekor\b', text, re.UNICODE):
            issues.append({
                "severity": "High",
                "category": "Untranslated term",
                "message":  '"Dekor" not localized in FR output',
            })

        return issues
