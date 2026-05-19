"""
extraction/orchestrator.py
--------------------------
Orchestrates the Week 2 extraction pipeline.
1. Fetch unprocessed transcripts from DB.
2. Diarize into executive blocks.
3. Extract sentences.
4. Classify each sentence.
5. Save statements to DB and mark transcript as processed.
"""

import sys
from pathlib import Path
from loguru import logger
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from storage.database import get_unprocessed_transcripts, insert_statement, mark_transcript_processed, get_connection
from extraction.diarizer import diarize_transcript
from extraction.statement_extractor import extract_sentences
from extraction.classifier import classify_statement

def run_extraction(limit: int = None):
    """
    Run extraction pipeline on unprocessed transcripts.
    """
    transcripts = get_unprocessed_transcripts()
    if not transcripts:
        logger.info("No unprocessed transcripts found in database.")
        return
        
    if limit:
        transcripts = transcripts[:limit]
        
    logger.info(f"Found {len(transcripts)} unprocessed transcripts. Starting extraction...")
    
    stats = {
        "transcripts_processed": 0,
        "speaker_blocks_found": 0,
        "statements_extracted": 0
    }
    
    for row in tqdm(transcripts, desc="Processing Transcripts"):
        transcript_id = row['id']
        company_id = row['company_id']
        quarter = row['quarter']
        year = row['year']
        raw_text = row['raw_text']
        
        if not raw_text or len(raw_text) < 100:
            logger.warning(f"Transcript ID {transcript_id} has empty or very short raw text. Skipping.")
            mark_transcript_processed(transcript_id)
            continue
            
        logger.debug(f"Processing transcript ID {transcript_id} ({quarter} {year})")
        
        # 1. Diarization
        speaker_blocks = diarize_transcript(raw_text, company_id)
        stats["speaker_blocks_found"] += len(speaker_blocks)
        
        statements_for_db = []
        
        # 2 & 3. Statement Extraction & Classification
        for block in speaker_blocks:
            sentences = extract_sentences(block["text"])
            for sentence in sentences:
                classification = classify_statement(sentence)
                
                statements_for_db.append({
                    "executive_id": block["executive_id"],
                    "text": sentence,
                    "statement_type": classification["statement_type"],
                    "sentiment": classification["sentiment"],
                    "sentiment_score": classification["sentiment_score"]
                })
        
        # 4. Insert into database
        for stmt in statements_for_db:
            insert_statement(
                executive_id=stmt["executive_id"],
                company_id=company_id,
                transcript_id=transcript_id,
                quarter=quarter,
                year=year,
                text=stmt["text"],
                statement_type=stmt["statement_type"],
                sentiment=stmt["sentiment"],
                sentiment_score=stmt["sentiment_score"]
            )
            
        stats["statements_extracted"] += len(statements_for_db)
        
        # 5. Mark as processed
        mark_transcript_processed(transcript_id)
        stats["transcripts_processed"] += 1
        
    logger.info("\n" + "="*60)
    logger.info("EXTRACTION COMPLETE — Summary")
    logger.info(f"  Transcripts processed: {stats['transcripts_processed']}")
    logger.info(f"  Executive blocks   : {stats['speaker_blocks_found']}")
    logger.info(f"  Statements saved   : {stats['statements_extracted']}")
    logger.info("="*60)

if __name__ == "__main__":
    run_extraction()
