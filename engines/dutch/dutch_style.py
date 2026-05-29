"""
Dutch style application — wraps nl_engine post-processing.
"""

from nl_engine import nl_post_process


def apply_nl_style(text: str, canonical: str = "") -> str:
    """
    Apply full Dutch post-processing pipeline:
    dekor → colors → furniture → forbidden → format → IJ digraph →
    post-colon lowercase → extended case normalization.
    """
    return nl_post_process(text, canonical)
