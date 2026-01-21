"""
Test script for the document ingestion pipeline.
Demonstrates the API usage for the meeting briefing agent.
"""

import os
from ingestion import DocumentIngestionPipeline


def main():
    # Initialize the pipeline
    pipeline = DocumentIngestionPipeline()

    print("=" * 60)
    print("Meeting Briefing Agent - Document Ingestion Test")
    print("=" * 60)

    # List all companies
    print("\n1. Companies in database:")
    companies = pipeline.list_companies()
    for company in companies:
        print(f"   - {company}")

    # Test query by company
    print("\n2. Query by company: 'Helix Therapeutics'")
    print("-" * 40)
    results = pipeline.query_by_company(
        "Helix Therapeutics",
        query_text="What is the clinical trial status?",
        n_results=3
    )
    for i, r in enumerate(results):
        print(f"\n   [{i+1}] Score: {r['similarity_score']}")
        print(f"       Type: {r['metadata'].get('document_type')}")
        print(f"       Preview: {r['content'][:150]}...")

    # Test get company summary
    print("\n\n3. Company Summary: 'CodeLayer'")
    print("-" * 40)
    summary = pipeline.get_company_summary("CodeLayer")
    print(f"   Total documents: {summary['total_documents']}")
    print(f"   - Profile chunks: {len(summary['profile'])}")
    print(f"   - News articles: {len(summary['news_articles'])}")
    print(f"   - Signal reports: {len(summary['signal_reports'])}")

    # Test semantic search
    print("\n\n4. Semantic Search: 'funding runway and cash position'")
    print("-" * 40)
    results = pipeline.semantic_search(
        "funding runway and cash position",
        n_results=5
    )
    for i, r in enumerate(results):
        print(f"\n   [{i+1}] Company: {r['metadata'].get('company_name')} | Score: {r['similarity_score']}")
        print(f"       Type: {r['metadata'].get('document_type')}")
        print(f"       Preview: {r['content'][:120]}...")

    # Test filtered semantic search
    print("\n\n5. Filtered Search: 'executive team' (signal_reports only)")
    print("-" * 40)
    results = pipeline.semantic_search(
        "executive team leadership changes",
        n_results=3,
        document_types=["signal_report"]
    )
    for i, r in enumerate(results):
        print(f"\n   [{i+1}] Company: {r['metadata'].get('company_name')} | Score: {r['similarity_score']}")
        print(f"       Signal Type: {r['metadata'].get('signal_type')}")
        print(f"       Preview: {r['content'][:120]}...")

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
