"""
Document Ingestion Pipeline for Meeting Briefing Agent

This module handles:
- Loading markdown documents from the mock_documents directory
- Parsing and extracting metadata (company name, document type, date)
- Chunking documents for embedding
- Creating embeddings using OpenAI text-embedding-3-small
- Storing in ChromaDB with metadata
- Querying by company name
"""

import os
import re
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from datetime import datetime
from typing import Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
from openai import OpenAI


# Configuration
DOCUMENTS_DIR = Path(__file__).parent.parent.parent / "data" / "mock_documents"
CHROMA_PERSIST_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "meeting_briefing_docs"
EMBEDDING_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 1000  # characters
CHUNK_OVERLAP = 200  # characters


class DocumentIngestionPipeline:
    """Pipeline for ingesting and querying meeting briefing documents."""

    def __init__(self, openai_api_key: Optional[str] = None):
        """
        Initialize the ingestion pipeline.

        Args:
            openai_api_key: OpenAI API key. If not provided, reads from OPENAI_API_KEY env var.
        """
        self.api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key must be provided or set in OPENAI_API_KEY env var")

        self.openai_client = OpenAI(api_key=self.api_key)

        # Set up OpenAI embedding function for consistent querying
        self.embedding_function = embedding_functions.OpenAIEmbeddingFunction(
            api_key=self.api_key,
            model_name=EMBEDDING_MODEL,
        )

        # Initialize ChromaDB with persistence
        CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        self.chroma_client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
        self.collection = self.chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
            embedding_function=self.embedding_function,
        )

    def extract_metadata(self, file_path: Path) -> dict:
        """
        Extract metadata from file path and content.

        Args:
            file_path: Path to the markdown file

        Returns:
            Dictionary containing extracted metadata
        """
        filename = file_path.stem
        parent_dir = file_path.parent.name

        # Determine document type from directory
        doc_type_map = {
            "company_profiles": "company_profile",
            "news_articles": "news_article",
            "signal_reports": "signal_report"
        }
        doc_type = doc_type_map.get(parent_dir, "unknown")

        # Extract company name from filename
        # Patterns: company_profile.md, company_news_YYYY-MM-DD.md, company_type_signal_YYYY-MM.md
        company_patterns = [
            r"^(.+?)_profile$",  # company_profile
            r"^(.+?)_news_\d{4}-\d{2}-\d{2}$",  # company_news_date
            r"^(.+?)_(?:hiring|competitive|regulatory|traction|clinical|financial|executive|customer|technology|market)_signal_\d{4}-\d{2}$",  # company_type_signal_date
        ]

        company_name = None
        for pattern in company_patterns:
            match = re.match(pattern, filename)
            if match:
                company_name = match.group(1).replace("_", " ").title()
                break

        if not company_name:
            # Fallback: use first part of filename
            company_name = filename.split("_")[0].replace("_", " ").title()

        # Extract date from filename if present
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
        if date_match:
            doc_date = date_match.group(1)
        else:
            # Try YYYY-MM format
            date_match = re.search(r"(\d{4}-\d{2})$", filename)
            if date_match:
                doc_date = date_match.group(1) + "-01"  # Default to first of month
            else:
                doc_date = None

        # Extract signal type for signal reports
        signal_type = None
        if doc_type == "signal_report":
            signal_match = re.search(r"_(\w+)_signal_", filename)
            if signal_match:
                signal_type = signal_match.group(1)

        return {
            "company_name": company_name,
            "document_type": doc_type,
            "date": doc_date,
            "signal_type": signal_type,
            "file_path": str(file_path),
            "filename": filename
        }

    def chunk_document(self, content: str, metadata: dict) -> list[dict]:
        """
        Split document into chunks with overlap.

        Args:
            content: Full document content
            metadata: Document metadata to attach to each chunk

        Returns:
            List of chunk dictionaries with content and metadata
        """
        chunks = []

        # Clean content
        content = content.strip()

        # If content is small enough, return as single chunk
        if len(content) <= CHUNK_SIZE:
            chunks.append({
                "content": content,
                "metadata": {**metadata, "chunk_index": 0, "total_chunks": 1}
            })
            return chunks

        # Split by sections (headers) first for better semantic chunking
        sections = re.split(r'\n(?=#{1,3}\s)', content)

        current_chunk = ""
        chunk_index = 0

        for section in sections:
            # If adding this section would exceed chunk size
            if len(current_chunk) + len(section) > CHUNK_SIZE:
                if current_chunk:
                    chunks.append({
                        "content": current_chunk.strip(),
                        "metadata": {**metadata, "chunk_index": chunk_index}
                    })
                    chunk_index += 1

                # If section itself is too large, split it further
                if len(section) > CHUNK_SIZE:
                    # Split by paragraphs
                    paragraphs = section.split('\n\n')
                    current_chunk = ""

                    for para in paragraphs:
                        if len(current_chunk) + len(para) > CHUNK_SIZE:
                            if current_chunk:
                                chunks.append({
                                    "content": current_chunk.strip(),
                                    "metadata": {**metadata, "chunk_index": chunk_index}
                                })
                                chunk_index += 1
                            current_chunk = para + "\n\n"
                        else:
                            current_chunk += para + "\n\n"
                else:
                    # Add overlap from previous chunk
                    if chunks:
                        overlap_text = chunks[-1]["content"][-CHUNK_OVERLAP:]
                        current_chunk = overlap_text + "\n" + section
                    else:
                        current_chunk = section
            else:
                current_chunk += "\n" + section

        # Add final chunk
        if current_chunk.strip():
            chunks.append({
                "content": current_chunk.strip(),
                "metadata": {**metadata, "chunk_index": chunk_index}
            })

        # Update total_chunks in all chunk metadata
        total_chunks = len(chunks)
        for chunk in chunks:
            chunk["metadata"]["total_chunks"] = total_chunks

        return chunks

    def create_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Create embeddings for a list of texts using OpenAI.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors
        """
        # OpenAI has a limit on batch size, process in batches
        batch_size = 100
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = self.openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=batch
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    def load_documents(self) -> list[dict]:
        """
        Load all markdown documents from the documents directory.

        Returns:
            List of document dictionaries with content and metadata
        """
        documents = []

        if not DOCUMENTS_DIR.exists():
            raise FileNotFoundError(f"Documents directory not found: {DOCUMENTS_DIR}")

        # Walk through all subdirectories
        for md_file in DOCUMENTS_DIR.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                metadata = self.extract_metadata(md_file)

                documents.append({
                    "content": content,
                    "metadata": metadata
                })
            except Exception as e:
                print(f"Error loading {md_file}: {e}")

        return documents

    def ingest(self, force_reingest: bool = False) -> dict:
        """
        Run the full ingestion pipeline.

        Args:
            force_reingest: If True, clear existing data and reingest

        Returns:
            Dictionary with ingestion statistics
        """
        if force_reingest:
            # Delete and recreate collection
            try:
                self.chroma_client.delete_collection(COLLECTION_NAME)
            except Exception:
                pass
            self.collection = self.chroma_client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )

        # Check if already ingested
        existing_count = self.collection.count()
        if existing_count > 0 and not force_reingest:
            return {
                "status": "skipped",
                "message": f"Collection already has {existing_count} documents. Use force_reingest=True to reingest.",
                "document_count": existing_count
            }

        # Load documents
        print("Loading documents...")
        documents = self.load_documents()
        print(f"Loaded {len(documents)} documents")

        # Chunk documents
        print("Chunking documents...")
        all_chunks = []
        for doc in documents:
            chunks = self.chunk_document(doc["content"], doc["metadata"])
            all_chunks.extend(chunks)
        print(f"Created {len(all_chunks)} chunks")

        # Create embeddings
        print("Creating embeddings...")
        texts = [chunk["content"] for chunk in all_chunks]
        embeddings = self.create_embeddings(texts)
        print(f"Created {len(embeddings)} embeddings")

        # Store in ChromaDB
        print("Storing in ChromaDB...")
        ids = [f"doc_{i}" for i in range(len(all_chunks))]

        # Prepare metadata (ChromaDB requires flat structure with primitive types)
        metadatas = []
        for chunk in all_chunks:
            meta = chunk["metadata"].copy()
            # Convert None values to empty strings for ChromaDB
            for key, value in meta.items():
                if value is None:
                    meta[key] = ""
            metadatas.append(meta)

        # Add to collection in batches
        batch_size = 100
        for i in range(0, len(all_chunks), batch_size):
            end_idx = min(i + batch_size, len(all_chunks))
            self.collection.add(
                ids=ids[i:end_idx],
                embeddings=embeddings[i:end_idx],
                documents=texts[i:end_idx],
                metadatas=metadatas[i:end_idx]
            )

        print("Ingestion complete!")

        return {
            "status": "success",
            "documents_loaded": len(documents),
            "chunks_created": len(all_chunks),
            "embeddings_created": len(embeddings)
        }

    def query_by_company(
        self,
        company_name: str,
        query_text: Optional[str] = None,
        n_results: int = 10,
        document_types: Optional[list[str]] = None
    ) -> list[dict]:
        """
        Query documents for a specific company.

        Args:
            company_name: Name of the company to query
            query_text: Optional semantic query text. If not provided, returns all docs for company.
            n_results: Maximum number of results to return
            document_types: Optional list of document types to filter (company_profile, news_article, signal_report)

        Returns:
            List of relevant document chunks with metadata and relevance scores
        """
        # Normalize company name for matching
        normalized_company = company_name.lower().replace(" ", "_").replace("-", "_")

        # Build where filter
        where_filter = {}

        # For company name, we need to handle the title case stored in metadata
        # ChromaDB doesn't support case-insensitive matching, so we'll filter post-query

        if document_types:
            if len(document_types) == 1:
                where_filter["document_type"] = document_types[0]
            else:
                where_filter["document_type"] = {"$in": document_types}

        # If query text provided, do semantic search
        if query_text:
            # Create embedding for query
            query_embedding = self.create_embeddings([query_text])[0]

            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results * 3,  # Get more results for filtering
                where=where_filter if where_filter else None,
                include=["documents", "metadatas", "distances"]
            )
        else:
            # Get all documents and filter by company
            # Use a generic query to get documents
            generic_query = f"{company_name} company information"
            query_embedding = self.create_embeddings([generic_query])[0]

            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results * 5,
                where=where_filter if where_filter else None,
                include=["documents", "metadatas", "distances"]
            )

        # Process and filter results
        processed_results = []
        seen_content = set()  # Deduplicate similar chunks

        if results and results["documents"]:
            for i, (doc, metadata, distance) in enumerate(zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0]
            )):
                # Filter by company name (case-insensitive)
                meta_company = metadata.get("company_name", "").lower().replace(" ", "_")
                if normalized_company not in meta_company and meta_company not in normalized_company:
                    continue

                # Skip near-duplicate content
                content_hash = hash(doc[:200])
                if content_hash in seen_content:
                    continue
                seen_content.add(content_hash)

                # Convert distance to similarity score (cosine distance to similarity)
                similarity = 1 - distance

                processed_results.append({
                    "content": doc,
                    "metadata": metadata,
                    "similarity_score": round(similarity, 4)
                })

                if len(processed_results) >= n_results:
                    break

        # Sort by similarity score
        processed_results.sort(key=lambda x: x["similarity_score"], reverse=True)

        return processed_results

    def semantic_search(
        self,
        query_text: str,
        n_results: int = 10,
        company_filter: Optional[str] = None,
        document_types: Optional[list[str]] = None
    ) -> list[dict]:
        """
        Perform semantic search across all documents.

        Args:
            query_text: The search query
            n_results: Maximum number of results
            company_filter: Optional company name to filter results
            document_types: Optional list of document types to filter

        Returns:
            List of relevant document chunks with metadata and scores
        """
        # Create embedding for query
        query_embedding = self.create_embeddings([query_text])[0]

        # Build where filter
        where_filter = {}
        if document_types:
            if len(document_types) == 1:
                where_filter["document_type"] = document_types[0]
            else:
                where_filter["document_type"] = {"$in": document_types}

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results * 2 if company_filter else n_results,
            where=where_filter if where_filter else None,
            include=["documents", "metadatas", "distances"]
        )

        processed_results = []

        if results and results["documents"]:
            for doc, metadata, distance in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0]
            ):
                # Filter by company if specified
                if company_filter:
                    normalized_filter = company_filter.lower().replace(" ", "_")
                    meta_company = metadata.get("company_name", "").lower().replace(" ", "_")
                    if normalized_filter not in meta_company and meta_company not in normalized_filter:
                        continue

                similarity = 1 - distance
                processed_results.append({
                    "content": doc,
                    "metadata": metadata,
                    "similarity_score": round(similarity, 4)
                })

                if len(processed_results) >= n_results:
                    break

        return processed_results

    def get_company_summary(self, company_name: str) -> dict:
        """
        Get a structured summary of all documents for a company.

        Args:
            company_name: Name of the company

        Returns:
            Dictionary with categorized document information
        """
        # Get all document types for the company
        profile = self.query_by_company(
            company_name,
            document_types=["company_profile"],
            n_results=5
        )

        news = self.query_by_company(
            company_name,
            document_types=["news_article"],
            n_results=10
        )

        signals = self.query_by_company(
            company_name,
            document_types=["signal_report"],
            n_results=10
        )

        return {
            "company_name": company_name,
            "profile": profile,
            "news_articles": news,
            "signal_reports": signals,
            "total_documents": len(profile) + len(news) + len(signals)
        }

    def list_companies(self) -> list[str]:
        """
        Get a list of all unique company names in the database.

        Returns:
            List of company names
        """
        # Get all metadata
        all_data = self.collection.get(include=["metadatas"])

        companies = set()
        if all_data and all_data["metadatas"]:
            for metadata in all_data["metadatas"]:
                company = metadata.get("company_name", "")
                if company:
                    companies.add(company)

        return sorted(list(companies))


def main():
    """Main function to run ingestion pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description="Document Ingestion Pipeline")
    parser.add_argument("--reingest", action="store_true", help="Force reingestion of all documents")
    parser.add_argument("--query", type=str, help="Query text for semantic search")
    parser.add_argument("--company", type=str, help="Company name to filter or query")
    parser.add_argument("--list-companies", action="store_true", help="List all companies in the database")
    args = parser.parse_args()

    # Initialize pipeline
    pipeline = DocumentIngestionPipeline()

    if args.list_companies:
        companies = pipeline.list_companies()
        print("\nCompanies in database:")
        for company in companies:
            print(f"  - {company}")
        return

    # Run ingestion
    result = pipeline.ingest(force_reingest=args.reingest)
    print(f"\nIngestion result: {result}")

    # Run query if provided
    if args.company:
        print(f"\n--- Documents for {args.company} ---")
        if args.query:
            results = pipeline.query_by_company(args.company, query_text=args.query)
        else:
            results = pipeline.query_by_company(args.company)

        for i, r in enumerate(results):
            print(f"\n[{i+1}] Score: {r['similarity_score']}")
            print(f"    Type: {r['metadata'].get('document_type')}")
            print(f"    Date: {r['metadata'].get('date', 'N/A')}")
            print(f"    Content: {r['content'][:200]}...")

    elif args.query:
        print(f"\n--- Search results for: {args.query} ---")
        results = pipeline.semantic_search(args.query)
        for i, r in enumerate(results):
            print(f"\n[{i+1}] Score: {r['similarity_score']}")
            print(f"    Company: {r['metadata'].get('company_name')}")
            print(f"    Type: {r['metadata'].get('document_type')}")
            print(f"    Content: {r['content'][:200]}...")


if __name__ == "__main__":
    main()
