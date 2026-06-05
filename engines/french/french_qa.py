"""
French QA engine.
Checks: German residue in FR output, untranslated terms.
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

        # Residual "Dekor" not localized
        if re.search(r'\bDekor\b', text, re.UNICODE):
            issues.append({
                "severity": "High",
                "category": "Untranslated term",
                "message":  '"Dekor" not localized in FR output',
            })

        return issues
