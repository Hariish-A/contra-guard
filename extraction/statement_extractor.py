"""
extraction/statement_extractor.py
---------------------------------
Takes a block of text (from diarizer) and splits it into individual sentences
using spaCy. Performs basic cleanup to make sentences ready for classification.
"""

import spacy
from loguru import logger

# Load the spaCy English model. 
# It must be downloaded via `python -m spacy download en_core_web_sm`
try:
    nlp = spacy.load("en_core_web_sm", disable=["ner", "textcat"]) # Disable unneeded pipes for speed
    nlp.add_pipe('sentencizer')
except OSError:
    logger.error("spaCy model 'en_core_web_sm' not found. Run: python -m spacy download en_core_web_sm")
    raise


def extract_sentences(text_block: str) -> list[str]:
    """
    Split a block of text into sentences using spaCy.
    Cleans up whitespace and ignores extremely short sentences.
    """
    # Clean up weird line breaks within the block first
    text_block = text_block.replace("\n", " ").strip()
    # Collapse multiple spaces
    import re
    text_block = re.sub(r'[ \t]+', ' ', text_block)
    
    doc = nlp(text_block)
    sentences = []
    
    for sent in doc.sents:
        s = sent.text.strip()
        # Filter out very short junk sentences (e.g. "Thank you.", "Yes.")
        if len(s) > 15:
            sentences.append(s)
            
    return sentences
