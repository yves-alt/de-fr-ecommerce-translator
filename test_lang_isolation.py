"""
Language isolation regression tests — NL must never contaminate FR output.
Run:  python test_lang_isolation.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import (
    detect_dutch_in_french,
    apply_dutch_to_french_fixes,
    DUTCH_IN_FRENCH_MAP,
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

failures = 0


def check(label: str, condition: bool) -> None:
    global failures
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}")
    if not condition:
        failures += 1


print("\n=== Language Isolation — Dutch-in-French detector ===\n")

# Test 1: basic Dutch color words detected
detected = detect_dutch_in_french("Canapé Bever 3 places")
check("'Bever' detected in French text", "Bever" in detected)

# Test 2: Dutch color word not detected in clean French
detected = detect_dutch_in_french("Canapé gris 3 places")
check("Clean French text has no Dutch words", detected == [])

# Test 3: multiple Dutch words detected
detected = detect_dutch_in_french("Kleur: Bruin / Grijs")
check("'Bruin' detected",  "Bruin" in detected)
check("'Grijs' detected",  "Grijs" in detected)

# Test 4: apply fixes — Dutch colors replaced
fixed, count = apply_dutch_to_french_fixes("Canapé Bever 3 places")
check("'Bever' → 'Castor'", "Castor" in fixed)
check("fix count > 0", count > 0)

# Test 5: Bruin → Marron
fixed, count = apply_dutch_to_french_fixes("Couleur: Bruin")
check("'Bruin' → 'Marron'", "Marron" in fixed)

# Test 6: Grijs → Gris
fixed, count = apply_dutch_to_french_fixes("Couleur: Grijs")
check("'Grijs' → 'Gris'", "Gris" in fixed)

# Test 7: Groen → Vert
fixed, count = apply_dutch_to_french_fixes("Groen frame")
check("'Groen' → 'Vert'", "Vert" in fixed)

# Test 8: Rood → Rouge
fixed, count = apply_dutch_to_french_fixes("Kleur Rood")
check("'Rood' → 'Rouge'", "Rouge" in fixed)

# Test 9: Fijnbever / Fijnbiber detected and replaced
fixed, count = apply_dutch_to_french_fixes("Fijnbever stof")
check("'Fijnbever' → 'castorette fine'", "castorette fine" in fixed)

fixed, count = apply_dutch_to_french_fixes("Fijnbiber materiaal")
check("'Fijnbiber' → 'castorette fine'", "castorette fine" in fixed)

# Test 10: Kerstdeken replaced
fixed, count = apply_dutch_to_french_fixes("Kerstdeken groot")
check("'Kerstdeken' → 'couverture de Noël'", "couverture de Noël" in fixed)

# Test 11: clean French text not mutated
fixed, count = apply_dutch_to_french_fixes("Canapé gris 3 places en tissu")
check("Clean French unchanged", fixed == "Canapé gris 3 places en tissu" and count == 0)

# Test 12: Dutch furniture terms
fixed, count = apply_dutch_to_french_fixes("Product: hoekbank")
check("'hoekbank' → 'canapé d'angle'", "canapé d'angle" in fixed)

# Test 13: Dutch map has no overlap with common French words
fr_words = {"le", "la", "les", "de", "du", "un", "une", "et", "en", "au"}
dutch_lower = {nl.lower() for nl, _ in DUTCH_IN_FRENCH_MAP}
overlap = fr_words & dutch_lower
check("No common French words in Dutch map", len(overlap) == 0)

# Test 14: detect_dutch_in_french returns empty list for numbers/dimensions
detected = detect_dutch_in_french("120 x 80 x 40 cm")
check("Dimensions not flagged as Dutch", detected == [])

print(f"\n{'='*50}")
print(f"Results: {14 - failures}/14 passed" + ("" if failures == 0 else f", {failures} FAILED"))
print()

sys.exit(1 if failures else 0)
