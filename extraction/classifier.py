"""
extraction/classifier.py
------------------------
Classifies extracted sentences into guidance types and scores their sentiment.

Models used:
- Sentiment: 'ProsusAI/finbert' (Positive, Negative, Neutral)
- Guidance Type: Rule-based keyword matching (as per config)
"""

import re
import torch
from transformers import pipeline
from loguru import logger
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import FINBERT_MODEL, GUIDANCE_KEYWORDS, HEDGE_SCALE

# Initialize the pipeline globally so it's only loaded once per process.
logger.info(f"Loading FinBERT sentiment model ({FINBERT_MODEL})...")
device = 0 if torch.cuda.is_available() else -1
sentiment_pipeline = pipeline("sentiment-analysis", model=FINBERT_MODEL, device=device)

def _get_guidance_type(sentence: str) -> str:
    """
    Classify the guidance type using rule-based keyword matching.
    Types: QUANTITATIVE_GUIDANCE, QUALITATIVE_GUIDANCE, HEDGED, DEFLECTION, FACTUAL_CLAIM
    """
    s_lower = sentence.lower()
    
    # 1. Deflection Check
    deflection_keywords = ["too early", "cannot comment", "wait and watch", "not in a position to give", "difficult to say"]
    if any(kw in s_lower for kw in deflection_keywords):
        return "DEFLECTION"
        
    # 2. Check for Hedging
    hedged_keywords = list(HEDGE_SCALE.keys())
    is_hedged = any(kw in s_lower for kw in hedged_keywords)
    
    # 3. Check for general guidance keywords
    is_guidance = any(kw in s_lower for kw in GUIDANCE_KEYWORDS)
    
    # 4. Check for Quantitative indicators (Numbers/Percentages)
    # Looks for digits or % sign
    is_quantitative = bool(re.search(r'\d+%?|\b(one|two|three|four|five|six|seven|eight|nine|ten|percent|basis points|bps)\b', s_lower))

    if is_guidance and is_quantitative:
        return "QUANTITATIVE_GUIDANCE"
    elif is_guidance:
        # If it has hedge words and guidance words, we can flag it as HEDGED or QUALITATIVE.
        if is_hedged:
            return "HEDGED"
        return "QUALITATIVE_GUIDANCE"
    elif is_hedged:
        return "HEDGED"
        
    # Fallback
    return "FACTUAL_CLAIM"


def classify_statement(sentence: str) -> dict:
    """
    Returns a dict with guidance type and sentiment score.
    """
    # Truncate to 512 tokens for BERT limit (approx 400 words)
    truncated_sentence = " ".join(sentence.split()[:400])
    
    # Run sentiment pipeline
    # FinBERT returns labels: 'positive', 'negative', 'neutral'
    try:
        result = sentiment_pipeline(truncated_sentence)[0]
        sentiment_label = result['label'].lower()
        sentiment_score = result['score']
    except Exception as e:
        logger.error(f"Sentiment classification failed: {e}")
        sentiment_label = "neutral"
        sentiment_score = 0.0
        
    statement_type = _get_guidance_type(sentence)
    
    return {
        "statement_type": statement_type,
        "sentiment": sentiment_label,
        "sentiment_score": sentiment_score
    }
