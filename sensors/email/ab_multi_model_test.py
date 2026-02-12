#!/usr/bin/env python3
"""
Multi-Model Embedding Comparison Test
Compares OpenAI vs multiple local models for email retrieval quality.
"""

import asyncio
import time
import numpy as np
from typing import List, Dict, Tuple, Optional
import sys
from pathlib import Path

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent))
from maildir_parser import MaildirParser


# Models to test
MODELS = {
    "openai": {
        "name": "OpenAI text-embedding-3-large",
        "type": "api",
        "dim": 1024,
        "privacy": "❌ Data sent to OpenAI",
    },
    "bge-large": {
        "name": "BAAI/bge-large-en-v1.5",
        "type": "local",
        "dim": 1024,
        "privacy": "✅ Local",
    },
    "bge-m3": {
        "name": "BAAI/bge-m3",
        "type": "local",
        "dim": 1024,
        "privacy": "✅ Local",
    },
    "nomic": {
        "name": "nomic-ai/nomic-embed-text-v1.5",
        "type": "local",
        "dim": 768,
        "privacy": "✅ Local + Open Data",
    },
}


class LocalEmbedder:
    """Local embedding using sentence-transformers."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    def load(self):
        if self._model is None:
            print(f"      Loading {self.model_name}...")
            start = time.time()
            from sentence_transformers import SentenceTransformer

            # Nomic requires trust_remote_code
            if "nomic" in self.model_name.lower():
                self._model = SentenceTransformer(self.model_name, trust_remote_code=True)
            else:
                self._model = SentenceTransformer(self.model_name)

            print(f"      Loaded in {time.time()-start:.1f}s")

    def embed(self, text: str) -> Tuple[List[float], float]:
        self.load()
        start = time.time()

        # Nomic requires specific prefix
        if "nomic" in self.model_name.lower():
            text = f"search_document: {text}"

        emb = self._model.encode(text, normalize_embeddings=True)
        latency = (time.time() - start) * 1000
        return emb.tolist(), latency

    def embed_query(self, text: str) -> List[float]:
        self.load()

        # Nomic requires specific prefix for queries
        if "nomic" in self.model_name.lower():
            text = f"search_query: {text}"

        return self._model.encode(text, normalize_embeddings=True).tolist()


class OpenAIEmbedder:
    """OpenAI embedding via local server."""

    def __init__(self, url: str = "http://localhost:8090/encode"):
        self.url = url
        self._client = None

    async def embed(self, text: str) -> Tuple[List[float], float]:
        import httpx
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)

        start = time.time()
        response = await self._client.post(self.url, json={"text": text})
        latency = (time.time() - start) * 1000

        if response.status_code == 200:
            return response.json()["embedding"], latency
        raise Exception(f"Error: {response.status_code}")

    async def close(self):
        if self._client:
            await self._client.aclose()


def cosine_similarity(a: List[float], b: List[float]) -> float:
    a = np.array(a)
    b = np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def rank_by_similarity(query_emb: List[float], doc_embs: List[List[float]]) -> List[int]:
    sims = [cosine_similarity(query_emb, doc) for doc in doc_embs]
    return list(np.argsort(sims)[::-1])


async def run_comparison():
    print("=" * 70)
    print("Multi-Model Embedding Comparison")
    print("=" * 70)

    # Load sample emails
    print("\n1. Loading sample emails...")
    parser = MaildirParser(base_path="~/Mail/Gmail", max_age_years=5)

    emails = []
    for email in parser.scan_all():
        if email and len(email.get('body_text', '')) > 100:
            emails.append(email)
            if len(emails) >= 15:
                break

    print(f"   Loaded {len(emails)} emails")

    texts = []
    for e in emails:
        subject = e.get('subject', '')
        body = e.get('body_text', '')[:500]
        texts.append(f"Subject: {subject}\n\n{body}")

    queries = [
        "carbon credits and climate change",
        "meeting invitation calendar",
        "order confirmation shipping delivery",
        "project status update report",
    ]

    # Initialize embedders
    embedders = {
        "openai": OpenAIEmbedder(),
        "bge-large": LocalEmbedder("BAAI/bge-large-en-v1.5"),
        "bge-m3": LocalEmbedder("BAAI/bge-m3"),
        "nomic": LocalEmbedder("nomic-ai/nomic-embed-text-v1.5"),
    }

    results = {}

    # Test each model
    for model_key, embedder in embedders.items():
        model_info = MODELS[model_key]
        print(f"\n2. Testing {model_info['name']}...")

        embeddings = []
        latencies = []

        try:
            for i, text in enumerate(texts):
                if model_key == "openai":
                    emb, lat = await embedder.embed(text)
                else:
                    emb, lat = embedder.embed(text)
                embeddings.append(emb)
                latencies.append(lat)
                print(f"   [{i+1}/{len(texts)}] {lat:.0f}ms", end="\r")

            # Embed queries
            query_embs = []
            for q in queries:
                if model_key == "openai":
                    qe, _ = await embedder.embed(q)
                else:
                    qe = embedder.embed_query(q)
                query_embs.append(qe)

            results[model_key] = {
                "embeddings": embeddings,
                "query_embs": query_embs,
                "latencies": latencies,
                "avg_latency": np.mean(latencies),
            }
            print(f"   Done. Avg latency: {np.mean(latencies):.0f}ms          ")

        except Exception as e:
            print(f"   Error: {e}")
            results[model_key] = None

    # Close async client
    await embedders["openai"].close()

    # Compare rankings
    print("\n" + "=" * 70)
    print("RETRIEVAL COMPARISON (vs OpenAI baseline)")
    print("=" * 70)

    if results.get("openai") is None:
        print("OpenAI baseline not available!")
        return

    openai_res = results["openai"]

    comparison_table = []

    for model_key, res in results.items():
        if res is None or model_key == "openai":
            continue

        agreements = []
        top1_matches = 0

        for qi, query in enumerate(queries):
            openai_ranking = rank_by_similarity(
                openai_res["query_embs"][qi],
                openai_res["embeddings"]
            )
            model_ranking = rank_by_similarity(
                res["query_embs"][qi],
                res["embeddings"]
            )

            # Top-5 overlap
            overlap = len(set(openai_ranking[:5]) & set(model_ranking[:5]))
            agreements.append(overlap / 5)

            # Top-1 match
            if openai_ranking[0] == model_ranking[0]:
                top1_matches += 1

        comparison_table.append({
            "model": model_key,
            "name": MODELS[model_key]["name"],
            "dim": MODELS[model_key]["dim"],
            "top5_agreement": np.mean(agreements) * 100,
            "top1_match": top1_matches / len(queries) * 100,
            "latency": res["avg_latency"],
            "privacy": MODELS[model_key]["privacy"],
        })

    # Print comparison table
    print("\n{:<12} {:<35} {:>5} {:>10} {:>10} {:>10}".format(
        "Model", "Name", "Dim", "Top-5 Agr", "Top-1 Match", "Latency"
    ))
    print("-" * 90)

    for row in comparison_table:
        print("{:<12} {:<35} {:>5} {:>9.0f}% {:>10.0f}% {:>8.0f}ms".format(
            row["model"],
            row["name"][:35],
            row["dim"],
            row["top5_agreement"],
            row["top1_match"],
            row["latency"],
        ))

    # Find best model
    print("\n" + "=" * 70)
    print("RECOMMENDATION")
    print("=" * 70)

    best = max(comparison_table, key=lambda x: x["top5_agreement"])

    print(f"\n   Best local model: {best['name']}")
    print(f"   - Top-5 agreement with OpenAI: {best['top5_agreement']:.0f}%")
    print(f"   - Top-1 match rate: {best['top1_match']:.0f}%")
    print(f"   - Latency: {best['latency']:.0f}ms")
    print(f"   - Privacy: {best['privacy']}")

    # Privacy recommendation
    print(f"\n   For personal emails, {best['model']} provides:")
    print(f"   ✅ Strong retrieval quality ({best['top5_agreement']:.0f}% agreement)")
    print(f"   ✅ Complete privacy - no data leaves your machine")


if __name__ == "__main__":
    asyncio.run(run_comparison())
