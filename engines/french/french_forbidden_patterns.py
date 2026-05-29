"""
French forbidden patterns — sourced from database.py _INITIAL_FORBIDDEN_FR.
"""

from intelligence import apply_forbidden_patterns

# FR forbidden patterns list (mirrors _INITIAL_FORBIDDEN_FR in database.py)
FR_FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    ("cuisine autonome",          "cuisine équipée"),
    ("chaiselongue",              "chaise longue"),
    ("assiettes à manger",        "assiettes"),
    ("assiette à manger",         "assiette"),
    ("boue",                      "argile"),
    ("table sans revêtement",     "table"),
    ("revêtu de poudre",          "thermolaqué"),
    ("revêtu par poudre",         "thermolaqué"),
    ("revêtement de poudre",      "thermolaqué"),
    ("laqué par poudre",          "thermolaqué"),
    ("traitement en poudre",      "thermolaqué"),
    ("thermopoudré",              "thermolaqué"),
    ("set consistant de",         "ensemble composé de"),
    ("ensemble consistant de",    "ensemble composé de"),
    ("paillasson en coco",        "couche de coco"),
    ("paillasson de coco",        "couche de coco"),
    ("nattes en coco",            "couche de coco"),
    ("décoration non comprise",   "accessoires non inclus"),
    ("chêne artisan décor",       "décor chêne artisan"),
    ("artisan chêne décor",       "décor chêne artisan"),
    ("chêne décor artisan",       "décor chêne artisan"),
    ("table à manger extensible", "table extensible"),
    ("cuisine autonome complète", "cuisine équipée complète"),
    ("pouf de pieds",             "repose-pieds"),
    ("support de pieds",          "repose-pieds"),
    ("housse amovible",           "revêtement amovible"),
    ("sans revêtement",           "sans finition"),
    ("meuble de télévision",      "meuble TV"),
    ("armoire de garde-robe",     "armoire"),
    ("structure en métal",        "structure métal"),
]


def apply_fr_forbidden(text: str, db_patterns: list | None = None) -> str:
    """
    Apply FR forbidden patterns.
    If db_patterns (from database) is provided, uses those.
    Falls back to the static FR_FORBIDDEN_PATTERNS list.
    """
    if db_patterns:
        return apply_forbidden_patterns(text, db_patterns, "French")
    # Apply static list as fallback
    import re
    for wrong, right in FR_FORBIDDEN_PATTERNS:
        if wrong.lower() not in text.lower():
            continue
        pat = re.compile(r'(?<!\w)' + re.escape(wrong) + r'(?!\w)', re.IGNORECASE | re.UNICODE)
        text = pat.sub(right, text)
    return text
