"""
Embeddings Module for News Aggregator
=====================================

Lightweight embedding computation for story classification and deduplication.
Designed for minimal runtime with aggressive caching.

## How Caching Prevents Duplicate Embeddings

1. **URL-based Cache**: Each embedding is cached by `md5(url)[:16]`
   - Same URL always returns cached embedding (no recomputation)
   - Cache is in-memory with optional database persistence

2. **Prototype Cache**: Type prototypes are embedded once at startup
   - Stored in memory as numpy arrays
   - Used for all similarity comparisons (no recomputation per story)

3. **Story-level Deduplication**: Combined with story_id hashing
   - Stories with same normalized URL + title + date bucket share embeddings
   - Prevents duplicate processing across clustering operations

## Model Selection

Primary: sentence-transformers (all-MiniLM-L6-v2)
- Fast, accurate, 384-dimensional embeddings
- ~50ms per embedding on CPU

Fallback: Hash-based embeddings
- Deterministic, no external dependencies
- Uses MD5 hashing to create pseudo-embeddings
- Less accurate but consistent

## Performance Characteristics

- First embedding: ~50ms (transformer) or ~5ms (hash)
- Cached embedding: ~0.1ms
- Prototype comparison: ~0.5ms (13 types * cosine similarity)
- Memory: ~20MB for model + ~10KB for prototype cache

Usage:
    from agents.news_aggregator.embeddings import EmbeddingService

    service = EmbeddingService()
    embedding = service.get_embedding("Title here", "Snippet text")
    similarity = service.cosine_similarity(embedding, prototype_embedding)
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from functools import lru_cache
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)

# =============================================================================
# TYPE PROTOTYPE PHRASES
# =============================================================================
# These phrases represent canonical examples of each Type classification.
# Embeddings are computed once at startup and used for similarity matching.

TYPE_PROTOTYPES: Dict[str, List[str]] = {
    'FUNDING': [
        "company raises Series A funding round",
        "startup secures $50 million in venture capital",
        "company valued at $1 billion after funding",
        "seed round investment led by top VC firm",
        "unicorn startup raises growth equity round",
        "company closes funding at higher valuation",
    ],
    'M&A': [
        "company acquired by larger tech firm",
        "merger announced between two companies",
        "acquisition deal completed for $500 million",
        "company bought by private equity firm",
        "strategic acquisition to expand market share",
        "tech giant buys startup in all-cash deal",
    ],
    'IPO': [
        "company files S-1 for initial public offering",
        "startup plans to go public on NASDAQ",
        "IPO priced at $20 per share",
        "company begins trading on NYSE today",
        "direct listing on stock exchange",
        "SPAC merger to take company public",
    ],
    'SECURITY': [
        "data breach exposes customer information",
        "security vulnerability discovered in software",
        "company hit by ransomware attack",
        "cyber attack compromises user accounts",
        "major outage affects service availability",
        "security incident under investigation",
    ],
    'LEGAL': [
        "company faces antitrust lawsuit",
        "FTC investigation into business practices",
        "class action lawsuit filed against company",
        "regulatory fine for compliance violation",
        "SEC investigation into financial reporting",
        "company settles lawsuit for $100 million",
    ],
    'LAYOFFS': [
        "company announces layoffs of 500 employees",
        "workforce reduction to cut costs",
        "restructuring results in job cuts",
        "company downsizes amid economic downturn",
        "layoffs affect 15% of staff",
        "headcount reduction announced by CEO",
    ],
    'HIRING': [
        "company plans to hire 1000 new employees",
        "new CEO appointed to lead company",
        "executive hire to lead product division",
        "company expanding team with new roles",
        "CTO joins from competitor company",
        "hiring spree as company scales operations",
    ],
    'PARTNERSHIP': [
        "strategic partnership announced between companies",
        "companies form alliance for new market",
        "integration partnership to expand features",
        "joint venture launched for product development",
        "collaboration agreement signed with partner",
        "companies team up on technology initiative",
    ],
    'PRODUCT': [
        "company launches new product feature",
        "product update introduces AI capabilities",
        "new version released with major improvements",
        "company debuts innovative product at conference",
        "product launch targets enterprise customers",
        "beta release available for early adopters",
    ],
    'EARNINGS': [
        "company reports quarterly revenue growth",
        "earnings beat analyst expectations",
        "annual revenue reaches $1 billion milestone",
        "profit margins improve year over year",
        "company achieves profitability for first time",
        "fiscal year results show strong performance",
    ],
    'CUSTOMER': [
        "company lands major enterprise deal",
        "customer win with Fortune 500 company",
        "new contract signed with government agency",
        "company expands into new market segment",
        "sales milestone reached with 1000 customers",
        "enterprise customer signs multi-year deal",
    ],
    'MARKET': [
        "industry report shows market growth",
        "sector analysis predicts consolidation",
        "regulatory changes affect industry players",
        "market trends indicate shifting demand",
        "industry outlook remains positive",
        "macro factors impact sector performance",
    ],
    'GENERAL': [
        "company news and updates",
        "business developments reported",
        "company mentioned in media coverage",
        "general news about the company",
    ],
}


# =============================================================================
# EMBEDDING SERVICE
# =============================================================================

class EmbeddingService:
    """
    Lightweight embedding service for story classification.

    Uses sentence-transformers if available, falls back to TF-IDF-like hashing.
    Caches embeddings by URL hash to prevent duplicate computation.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize embedding service.

        Args:
            model_name: SentenceTransformer model name (default: all-MiniLM-L6-v2)
        """
        self.model_name = model_name
        self._model = None
        self._use_transformer = False
        self._embedding_dim = 384  # Default for MiniLM

        # In-memory caches
        self._url_cache: Dict[str, np.ndarray] = {}
        self._prototype_cache: Dict[str, np.ndarray] = {}

        # Timing stats
        self.total_embedding_time_ms = 0
        self.embedding_count = 0
        self.cache_hits = 0

        # Initialize model
        self._init_model()

        # Pre-compute prototype embeddings
        self._init_prototype_embeddings()

    def _init_model(self):
        """Initialize the embedding model."""
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            self._use_transformer = True
            self._embedding_dim = self._model.get_sentence_embedding_dimension()
            logger.info(f"Loaded SentenceTransformer model: {self.model_name} (dim={self._embedding_dim})")
        except ImportError:
            logger.warning("sentence-transformers not available, using hash-based fallback")
            self._use_transformer = False
            self._embedding_dim = 256  # Hash-based dim

    def _init_prototype_embeddings(self):
        """Pre-compute embeddings for all Type prototypes."""
        logger.info("Computing prototype embeddings...")
        start = time.time()

        for type_name, phrases in TYPE_PROTOTYPES.items():
            # Compute embedding for each phrase, then average
            phrase_embeddings = []
            for phrase in phrases:
                emb = self._compute_embedding_raw(phrase)
                phrase_embeddings.append(emb)

            # Average embeddings for the Type
            self._prototype_cache[type_name] = np.mean(phrase_embeddings, axis=0)

        elapsed_ms = int((time.time() - start) * 1000)
        logger.info(f"Prototype embeddings computed in {elapsed_ms}ms")

    def _compute_embedding_raw(self, text: str) -> np.ndarray:
        """Compute embedding without caching."""
        if not text:
            return np.zeros(self._embedding_dim)

        if self._use_transformer:
            embedding = self._model.encode(text, convert_to_numpy=True)
            return embedding
        else:
            # Fallback: hash-based embedding (deterministic)
            return self._hash_embedding(text)

    def _hash_embedding(self, text: str) -> np.ndarray:
        """Create a deterministic hash-based embedding."""
        # Normalize text
        text = text.lower().strip()
        words = text.split()

        # Create embedding via multiple hash functions
        embedding = np.zeros(self._embedding_dim)

        for i, word in enumerate(words):
            # Hash each word to multiple positions
            for j in range(3):
                h = hashlib.md5(f"{word}_{j}".encode()).digest()
                # Use hash bytes to set embedding values
                for k in range(min(16, self._embedding_dim - (j * 16))):
                    idx = (j * 16 + k) % self._embedding_dim
                    embedding[idx] += (h[k] / 255.0 - 0.5) / (i + 1)

        # Normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        return embedding

    def get_url_hash(self, url: str) -> str:
        """Get hash key for URL-based caching."""
        return hashlib.md5(url.encode()).hexdigest()[:16]

    def get_embedding(
        self,
        title: str,
        snippet: str = "",
        url: str = None,
        use_cache: bool = True
    ) -> np.ndarray:
        """
        Get embedding for title + snippet.

        Args:
            title: Article title
            snippet: Article snippet/description
            url: Optional URL for caching
            use_cache: Whether to use/update cache

        Returns:
            Embedding vector as numpy array
        """
        # Check cache
        cache_key = None
        if use_cache and url:
            cache_key = self.get_url_hash(url)
            if cache_key in self._url_cache:
                self.cache_hits += 1
                return self._url_cache[cache_key]

        # Combine title and snippet
        text = f"{title} {snippet}".strip()

        # Compute embedding
        start = time.time()
        embedding = self._compute_embedding_raw(text)
        elapsed_ms = int((time.time() - start) * 1000)

        self.total_embedding_time_ms += elapsed_ms
        self.embedding_count += 1

        # Cache result
        if cache_key:
            self._url_cache[cache_key] = embedding

        return embedding

    def get_prototype_embedding(self, type_name: str) -> Optional[np.ndarray]:
        """Get cached prototype embedding for a Type."""
        return self._prototype_cache.get(type_name)

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        if a is None or b is None:
            return 0.0

        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return float(np.dot(a, b) / (norm_a * norm_b))

    def get_type_similarities(
        self,
        embedding: np.ndarray
    ) -> Dict[str, float]:
        """
        Compute similarity scores against all Type prototypes.

        Args:
            embedding: Story embedding vector

        Returns:
            Dict of {Type: similarity_score}
        """
        similarities = {}
        for type_name, proto_emb in self._prototype_cache.items():
            similarities[type_name] = self.cosine_similarity(embedding, proto_emb)
        return similarities

    def get_best_type_match(
        self,
        embedding: np.ndarray,
        exclude_types: List[str] = None
    ) -> Tuple[str, float]:
        """
        Find the best matching Type for an embedding.

        Args:
            embedding: Story embedding vector
            exclude_types: Types to exclude from matching

        Returns:
            Tuple of (type_name, similarity_score)
        """
        exclude = set(exclude_types or [])
        similarities = self.get_type_similarities(embedding)

        best_type = 'GENERAL'
        best_score = 0.0

        for type_name, score in similarities.items():
            if type_name in exclude:
                continue
            if score > best_score:
                best_type = type_name
                best_score = score

        return best_type, best_score

    def get_stats(self) -> Dict[str, any]:
        """Get timing and cache statistics."""
        return {
            'embedding_count': self.embedding_count,
            'cache_hits': self.cache_hits,
            'total_embedding_time_ms': self.total_embedding_time_ms,
            'avg_embedding_time_ms': (
                self.total_embedding_time_ms / self.embedding_count
                if self.embedding_count > 0 else 0
            ),
            'cache_size': len(self._url_cache),
            'using_transformer': self._use_transformer,
            'model_name': self.model_name if self._use_transformer else 'hash-based',
        }

    def clear_cache(self):
        """Clear the URL embedding cache."""
        self._url_cache.clear()
        self.cache_hits = 0


# =============================================================================
# MODULE-LEVEL SINGLETON
# =============================================================================

_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get or create the singleton embedding service."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def get_embedding(title: str, snippet: str = "", url: str = None) -> np.ndarray:
    """Convenience function to get embedding."""
    return get_embedding_service().get_embedding(title, snippet, url)


def get_type_similarities(embedding: np.ndarray) -> Dict[str, float]:
    """Convenience function to get Type similarities."""
    return get_embedding_service().get_type_similarities(embedding)
