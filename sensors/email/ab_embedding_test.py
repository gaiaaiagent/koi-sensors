#!/usr/bin/env python3
"""
A/B Embedding Comparison Test
Compares OpenAI vs Local BGE embeddings for email retrieval quality.
"""

import asyncio
import time
import numpy as np
import httpx
from typing import List, Dict, Tuple
import sys
from pathlib import Path

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent))
from maildir_parser import MaildirParser


# Server endpoints
OPENAI_SERVER = "http://localhost:8090/encode"
LOCAL_BGE_SERVER = "http://localhost:8091/encode"


async def get_embedding(client: httpx.AsyncClient, url: str, text: str) -> Tuple[List[float], float]:
    """Get embedding from server, return (embedding, latency_ms)."""
    start = time.time()
    response = await client.post(url, json={"text": text})
    latency = (time.time() - start) * 1000

    if response.status_code == 200:
        data = response.json()
        return data["embedding"], latency
    else:
        raise Exception(f"Server error: {response.status_code}")


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def rank_by_similarity(query_emb: List[float], doc_embs: List[List[float]]) -> List[int]:
    """Rank documents by similarity to query, return indices."""
    sims = [cosine_similarity(query_emb, doc) for doc in doc_embs]
    return list(np.argsort(sims)[::-1])  # Descending order


async def run_comparison():
    """Run A/B comparison test."""
    print("=" * 60)
    print("A/B Embedding Comparison: OpenAI vs Local BGE")
    print("=" * 60)

    # Load sample emails
    print("\n1. Loading sample emails...")
    parser = MaildirParser(
        base_path="~/Mail/Gmail",
        max_age_years=5,
    )

    emails = []
    for email in parser.scan_all():
        if email and len(email.get('body_text', '')) > 100:
            emails.append(email)
            if len(emails) >= 20:  # Sample size
                break

    print(f"   Loaded {len(emails)} emails")

    # Prepare texts
    texts = []
    for e in emails:
        subject = e.get('subject', '')
        body = e.get('body_text', '')[:500]  # Truncate for speed
        texts.append(f"Subject: {subject}\n\n{body}")

    # Test queries
    queries = [
        "carbon credits and climate",
        "meeting invitation schedule",
        "order confirmation shipping",
        "project update status report",
    ]

    print(f"   Using {len(queries)} test queries")

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 2. Embed with OpenAI
        print("\n2. Embedding with OpenAI (text-embedding-3-large)...")
        openai_embeddings = []
        openai_latencies = []

        for i, text in enumerate(texts):
            try:
                emb, lat = await get_embedding(client, OPENAI_SERVER, text)
                openai_embeddings.append(emb)
                openai_latencies.append(lat)
                print(f"   [{i+1}/{len(texts)}] {lat:.0f}ms", end="\r")
            except Exception as e:
                print(f"   Error: {e}")
                openai_embeddings.append(None)

        print(f"   Done. Avg latency: {np.mean(openai_latencies):.0f}ms")

        # Embed queries with OpenAI
        openai_query_embs = []
        for q in queries:
            emb, _ = await get_embedding(client, OPENAI_SERVER, q)
            openai_query_embs.append(emb)

        # 3. Embed with Local BGE
        print("\n3. Embedding with Local BGE (bge-large-en-v1.5)...")
        bge_embeddings = []
        bge_latencies = []

        for i, text in enumerate(texts):
            try:
                emb, lat = await get_embedding(client, LOCAL_BGE_SERVER, text)
                bge_embeddings.append(emb)
                bge_latencies.append(lat)
                print(f"   [{i+1}/{len(texts)}] {lat:.0f}ms", end="\r")
            except Exception as e:
                print(f"   Error: {e}")
                bge_embeddings.append(None)

        print(f"   Done. Avg latency: {np.mean(bge_latencies):.0f}ms")

        # Embed queries with BGE
        bge_query_embs = []
        for q in queries:
            emb, _ = await get_embedding(client, LOCAL_BGE_SERVER, q)
            bge_query_embs.append(emb)

    # 4. Compare embeddings directly
    print("\n4. Comparing embedding similarity...")
    direct_sims = []
    for i, (oe, be) in enumerate(zip(openai_embeddings, bge_embeddings)):
        if oe and be:
            sim = cosine_similarity(oe, be)
            direct_sims.append(sim)

    print(f"   OpenAI vs BGE embedding similarity:")
    print(f"   - Mean: {np.mean(direct_sims):.4f}")
    print(f"   - Min:  {np.min(direct_sims):.4f}")
    print(f"   - Max:  {np.max(direct_sims):.4f}")

    # 5. Compare retrieval rankings
    print("\n5. Comparing retrieval rankings...")
    print("-" * 60)

    ranking_agreements = []

    for qi, query in enumerate(queries):
        print(f"\n   Query: \"{query}\"")

        # Get rankings from both
        openai_ranking = rank_by_similarity(openai_query_embs[qi], openai_embeddings)
        bge_ranking = rank_by_similarity(bge_query_embs[qi], bge_embeddings)

        # Compare top-5
        openai_top5 = set(openai_ranking[:5])
        bge_top5 = set(bge_ranking[:5])
        overlap = len(openai_top5 & bge_top5)

        ranking_agreements.append(overlap / 5)

        print(f"   OpenAI top-5: {openai_ranking[:5]}")
        print(f"   BGE top-5:    {bge_ranking[:5]}")
        print(f"   Overlap: {overlap}/5 ({overlap*20}%)")

        # Show top result from each
        oi = openai_ranking[0]
        bi = bge_ranking[0]
        print(f"   OpenAI #1: {emails[oi]['subject'][:50]}...")
        print(f"   BGE #1:    {emails[bi]['subject'][:50]}...")

    # 6. Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print(f"\n   Embedding Similarity (OpenAI vs BGE): {np.mean(direct_sims):.2%}")
    print(f"   Top-5 Ranking Agreement: {np.mean(ranking_agreements):.2%}")

    print(f"\n   Latency Comparison:")
    print(f"   - OpenAI: {np.mean(openai_latencies):.0f}ms avg")
    print(f"   - Local BGE: {np.mean(bge_latencies):.0f}ms avg")

    print(f"\n   Privacy:")
    print(f"   - OpenAI: Data sent to OpenAI servers")
    print(f"   - Local BGE: All data stays on your machine ✓")

    # Recommendation
    agreement = np.mean(ranking_agreements)
    if agreement >= 0.8:
        print(f"\n   ✅ RECOMMENDATION: Use Local BGE")
        print(f"      Retrieval quality is nearly identical ({agreement:.0%} agreement)")
        print(f"      Your email data stays private")
    elif agreement >= 0.6:
        print(f"\n   ⚠️  RECOMMENDATION: Local BGE is acceptable")
        print(f"      Retrieval quality is similar ({agreement:.0%} agreement)")
        print(f"      Privacy benefits may outweigh small quality difference")
    else:
        print(f"\n   ⚠️  NOTE: Some ranking differences detected ({agreement:.0%} agreement)")
        print(f"      Consider testing with your specific use cases")


if __name__ == "__main__":
    asyncio.run(run_comparison())
