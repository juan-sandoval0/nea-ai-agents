"""
Meeting Briefing Agent - LangChain Tools
=========================================
This module provides three specialized tools for retrieving company information
from a ChromaDB vector store, designed for use with LangChain agents.

Tools:
1. get_company_profile - Retrieves company overview information
2. get_recent_news - Retrieves recent news articles
3. get_key_signals - Retrieves signal reports

Requirements:
- langchain
- chromadb
- python-dateutil (for date parsing)
"""

import os
from langchain_core.tools import Tool, StructuredTool
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class MeetingBriefingTools:
    """
    A collection of LangChain tools for retrieving company briefing materials
    from a ChromaDB vector store.

    Uses OpenAI embeddings (text-embedding-3-small) to match the ingestion pipeline.
    """

    EMBEDDING_MODEL = "text-embedding-3-small"

    def __init__(
        self,
        chroma_client: Optional[chromadb.Client] = None,
        collection_name: str = "company_documents",
        persist_directory: Optional[str] = None,
        openai_api_key: Optional[str] = None,
    ):
        """
        Initialize the meeting briefing tools.

        Args:
            chroma_client: Existing ChromaDB client (optional)
            collection_name: Name of the ChromaDB collection
            persist_directory: Path to persist ChromaDB data (if creating new client)
            openai_api_key: OpenAI API key for embeddings (default: from OPENAI_API_KEY env var)
        """
        # Set up OpenAI embedding function to match ingestion pipeline
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        if not self.openai_api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY env var or pass openai_api_key.")

        self.embedding_function = embedding_functions.OpenAIEmbeddingFunction(
            api_key=self.openai_api_key,
            model_name=self.EMBEDDING_MODEL,
        )

        if chroma_client is None:
            if persist_directory:
                self.client = chromadb.PersistentClient(path=persist_directory)
            else:
                self.client = chromadb.Client()
        else:
            self.client = chroma_client

        self.collection_name = collection_name
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"description": "Company documents for meeting briefings"},
            embedding_function=self.embedding_function,
        )
    
    def _format_results(
        self,
        results: Dict[str, Any],
        max_results: int = 5
    ) -> str:
        """
        Format ChromaDB query results into a readable string with source attribution.
        
        Args:
            results: ChromaDB query results dictionary
            max_results: Maximum number of results to include
            
        Returns:
            Formatted string with results and sources
        """
        if not results or not results.get('documents'):
            return "No results found."
        
        documents = results['documents'][0][:max_results]
        metadatas = results['metadatas'][0][:max_results] if results.get('metadatas') else []
        distances = results['distances'][0][:max_results] if results.get('distances') else []
        
        formatted_output = []
        
        for idx, doc in enumerate(documents):
            metadata = metadatas[idx] if idx < len(metadatas) else {}
            distance = distances[idx] if idx < len(distances) else None
            
            # Build result entry
            entry = f"\n--- Result {idx + 1} ---\n"
            entry += f"Content: {doc}\n"
            
            # Add source attribution
            if metadata:
                entry += "\nSource Information:\n"
                for key, value in metadata.items():
                    entry += f"  • {key}: {value}\n"
            
            # Add relevance score if available
            if distance is not None:
                relevance_score = 1 - distance  # Convert distance to similarity
                entry += f"  • Relevance Score: {relevance_score:.2f}\n"
            
            formatted_output.append(entry)
        
        return "\n".join(formatted_output)
    
    def get_company_profile(self, company_name: str) -> str:
        """
        Retrieve company overview information from the vector store.
        
        This tool searches for company profile documents that provide
        general information about the company, such as description,
        industry, key executives, and business model.
        
        Args:
            company_name: Name of the company to retrieve profile for
            
        Returns:
            Formatted string containing company profile information with sources
        """
        try:
            # Query the collection with filters
            results = self.collection.query(
                query_texts=[f"company profile overview for {company_name}"],
                n_results=5,
                where={
                    "$and": [
                        {"document_type": {"$eq": "profile"}},
                        {"company_name": {"$eq": company_name}}
                    ]
                }
            )
            
            if not results or not results.get('documents') or not results['documents'][0]:
                return f"No company profile found for: {company_name}"
            
            formatted = f"COMPANY PROFILE: {company_name}\n"
            formatted += "=" * 50 + "\n"
            formatted += self._format_results(results)
            
            return formatted
            
        except Exception as e:
            return f"Error retrieving company profile: {str(e)}"
    
    def get_recent_news(self, company_name: str, days: int = 30) -> str:
        """
        Retrieve recent news articles about a company.
        
        This tool searches for news articles published within the specified
        time window, filtered by document type and company name.
        
        Args:
            company_name: Name of the company to retrieve news for
            days: Number of days to look back (default: 30)
            
        Returns:
            Formatted string containing recent news articles with sources
        """
        try:
            # Calculate cutoff date as Unix timestamp (ChromaDB requires numeric for $gte)
            cutoff_date = datetime.now() - timedelta(days=days)
            cutoff_timestamp = cutoff_date.timestamp()

            # Query the collection with filters
            results = self.collection.query(
                query_texts=[f"recent news about {company_name}"],
                n_results=10,
                where={
                    "$and": [
                        {"document_type": {"$eq": "news"}},
                        {"company_name": {"$eq": company_name}},
                        {"date_timestamp": {"$gte": cutoff_timestamp}}
                    ]
                }
            )
            
            if not results or not results.get('documents') or not results['documents'][0]:
                return f"No recent news found for: {company_name} (last {days} days)"
            
            formatted = f"RECENT NEWS: {company_name} (Last {days} Days)\n"
            formatted += "=" * 50 + "\n"
            formatted += self._format_results(results, max_results=10)
            
            return formatted
            
        except Exception as e:
            return f"Error retrieving recent news: {str(e)}"
    
    def get_key_signals(self, company_name: str) -> str:
        """
        Retrieve key signal reports for a company.
        
        This tool searches for signal documents that contain important
        indicators, trends, or strategic insights about the company.
        
        Args:
            company_name: Name of the company to retrieve signals for
            
        Returns:
            Formatted string containing signal reports with sources
        """
        try:
            # Query the collection with filters
            results = self.collection.query(
                query_texts=[f"key signals and strategic insights for {company_name}"],
                n_results=7,
                where={
                    "$and": [
                        {"document_type": {"$eq": "signal"}},
                        {"company_name": {"$eq": company_name}}
                    ]
                }
            )
            
            if not results or not results.get('documents') or not results['documents'][0]:
                return f"No key signals found for: {company_name}"
            
            formatted = f"KEY SIGNALS: {company_name}\n"
            formatted += "=" * 50 + "\n"
            formatted += self._format_results(results, max_results=7)
            
            return formatted
            
        except Exception as e:
            return f"Error retrieving key signals: {str(e)}"
    
    def get_langchain_tools(self) -> List[Tool]:
        """
        Create and return LangChain Tool objects for all three retrieval functions.
        
        Returns:
            List of LangChain Tool objects ready to use with agents
        """
        tools = [
            Tool(
                name="get_company_profile",
                func=self.get_company_profile,
                description=(
                    "Retrieves comprehensive company profile information including "
                    "overview, industry, executives, and business model. "
                    "Input should be the company name as a string. "
                    "Use this tool when you need general background information about a company."
                )
            ),
            Tool(
                name="get_recent_news",
                func=lambda company_name: self.get_recent_news(company_name, days=30),
                description=(
                    "Retrieves recent news articles about a company from the last 30 days. "
                    "Input should be the company name as a string. "
                    "Use this tool when you need to understand recent developments, "
                    "announcements, or events related to the company."
                )
            ),
            Tool(
                name="get_key_signals",
                func=self.get_key_signals,
                description=(
                    "Retrieves key strategic signals and important indicators about a company. "
                    "Input should be the company name as a string. "
                    "Use this tool when you need to understand trends, strategic insights, "
                    "or important business indicators for the company."
                )
            )
        ]
        
        return tools


# Pydantic models for structured tool inputs (optional, for better type safety)
class CompanyProfileInput(BaseModel):
    """Input schema for get_company_profile tool"""
    company_name: str = Field(description="Name of the company to retrieve profile for")


class RecentNewsInput(BaseModel):
    """Input schema for get_recent_news tool"""
    company_name: str = Field(description="Name of the company to retrieve news for")
    days: int = Field(default=30, description="Number of days to look back for news")


class KeySignalsInput(BaseModel):
    """Input schema for get_key_signals tool"""
    company_name: str = Field(description="Name of the company to retrieve signals for")


def create_structured_tools(
    chroma_client: Optional[chromadb.Client] = None,
    collection_name: str = "company_documents",
    persist_directory: Optional[str] = None
) -> List[Tool]:
    """
    Convenience function to create structured LangChain tools with Pydantic schemas.
    
    Args:
        chroma_client: Existing ChromaDB client (optional)
        collection_name: Name of the ChromaDB collection
        persist_directory: Path to persist ChromaDB data
        
    Returns:
        List of structured LangChain Tool objects
    """
    briefing_tools = MeetingBriefingTools(
        chroma_client=chroma_client,
        collection_name=collection_name,
        persist_directory=persist_directory
    )
    
    structured_tools = [
        StructuredTool(
            name="get_company_profile",
            func=briefing_tools.get_company_profile,
            description=(
                "Retrieves comprehensive company profile information including "
                "overview, industry, executives, and business model. "
                "Use this tool when you need general background information about a company."
            ),
            args_schema=CompanyProfileInput
        ),
        StructuredTool(
            name="get_recent_news",
            func=briefing_tools.get_recent_news,
            description=(
                "Retrieves recent news articles about a company. "
                "Use this tool when you need to understand recent developments, "
                "announcements, or events related to the company."
            ),
            args_schema=RecentNewsInput
        ),
        StructuredTool(
            name="get_key_signals",
            func=briefing_tools.get_key_signals,
            description=(
                "Retrieves key strategic signals and important indicators about a company. "
                "Use this tool when you need to understand trends, strategic insights, "
                "or important business indicators for the company."
            ),
            args_schema=KeySignalsInput
        )
    ]
    
    return structured_tools


# Example usage
if __name__ == "__main__":
    # Example 1: Basic usage with standard tools
    print("Example 1: Creating standard LangChain tools\n")
    
    # Initialize the tools
    briefing_tools = MeetingBriefingTools(
        persist_directory="./chroma_db"
    )
    
    # Get LangChain tools
    tools = briefing_tools.get_langchain_tools()
    
    print(f"Created {len(tools)} tools:")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description[:80]}...")
    
    # Example 2: Using the tools directly
    print("\n" + "="*80)
    print("Example 2: Direct tool usage\n")
    
    company = "Acme Corp"
    
    print(f"Getting company profile for {company}:")
    profile = briefing_tools.get_company_profile(company)
    print(profile)
    
    print(f"\n\nGetting recent news for {company}:")
    news = briefing_tools.get_recent_news(company, days=30)
    print(news)
    
    print(f"\n\nGetting key signals for {company}:")
    signals = briefing_tools.get_key_signals(company)
    print(signals)
    
    # Example 3: Using with LangChain agent
    print("\n" + "="*80)
    print("Example 3: Integration with LangChain agent\n")
    print("""
    from langchain.agents import initialize_agent, AgentType
    from langchain.llms import OpenAI
    
    # Initialize your LLM
    llm = OpenAI(temperature=0)
    
    # Create the tools
    briefing_tools = MeetingBriefingTools(persist_directory="./chroma_db")
    tools = briefing_tools.get_langchain_tools()
    
    # Initialize the agent
    agent = initialize_agent(
        tools=tools,
        llm=llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True
    )
    
    # Use the agent
    response = agent.run(
        "Prepare a meeting briefing for Acme Corp including their profile, "
        "recent news, and key strategic signals"
    )
    print(response)
    """)
