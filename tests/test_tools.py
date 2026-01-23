"""
Test Suite for Meeting Briefing Tools
======================================
Run these tests to validate your ChromaDB setup and tool functionality.

Usage:
    python test_tools.py
    
    Or with pytest:
    pytest test_tools.py -v
"""

import unittest
from datetime import datetime, timedelta
import chromadb
from tools.meeting_briefing_tools import MeetingBriefingTools, create_structured_tools


class TestMeetingBriefingTools(unittest.TestCase):
    """Test suite for meeting briefing tools"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test database with sample data"""
        print("\nSetting up test database...")
        
        # Create test client
        cls.client = chromadb.Client()
        cls.collection = cls.client.get_or_create_collection(
            name="test_company_documents"
        )
        
        # Add test documents
        test_docs = [
            {
                "id": "test_profile_1",
                "document": "TestCo is a software company founded in 2020. CEO: Alice Johnson.",
                "metadata": {
                    "document_type": "profile",
                    "company_name": "TestCo",
                    "source": "Test Source"
                }
            },
            {
                "id": "test_news_1",
                "document": "TestCo launches new product with 50% performance improvement.",
                "metadata": {
                    "document_type": "news",
                    "company_name": "TestCo",
                    "source": "Tech News",
                    "date": datetime.now().isoformat()
                }
            },
            {
                "id": "test_news_2",
                "document": "TestCo announces partnership with MegaCorp.",
                "metadata": {
                    "document_type": "news",
                    "company_name": "TestCo",
                    "source": "Business Wire",
                    "date": (datetime.now() - timedelta(days=10)).isoformat()
                }
            },
            {
                "id": "test_signal_1",
                "document": "Growth signal: TestCo shows 200% YoY revenue increase.",
                "metadata": {
                    "document_type": "signal",
                    "company_name": "TestCo",
                    "source": "Analysis",
                    "signal_type": "growth"
                }
            }
        ]
        
        for doc in test_docs:
            cls.collection.add(
                ids=[doc["id"]],
                documents=[doc["document"]],
                metadatas=[doc["metadata"]]
            )
        
        print(f"Added {len(test_docs)} test documents")
    
    def setUp(self):
        """Set up tools for each test"""
        self.tools = MeetingBriefingTools(
            chroma_client=self.client,
            collection_name="test_company_documents"
        )
    
    def test_01_get_company_profile(self):
        """Test company profile retrieval"""
        print("\n--- Test 1: Company Profile ---")
        result = self.tools.get_company_profile("TestCo")
        
        # Assertions
        self.assertIsInstance(result, str)
        self.assertIn("TestCo", result)
        self.assertIn("COMPANY PROFILE", result)
        print("✓ Company profile retrieved successfully")
        print(f"Result length: {len(result)} characters")
    
    def test_02_get_recent_news(self):
        """Test recent news retrieval"""
        print("\n--- Test 2: Recent News ---")
        result = self.tools.get_recent_news("TestCo", days=30)
        
        # Assertions
        self.assertIsInstance(result, str)
        self.assertIn("TestCo", result)
        self.assertIn("RECENT NEWS", result)
        print("✓ Recent news retrieved successfully")
        print(f"Result length: {len(result)} characters")
    
    def test_03_get_key_signals(self):
        """Test key signals retrieval"""
        print("\n--- Test 3: Key Signals ---")
        result = self.tools.get_key_signals("TestCo")
        
        # Assertions
        self.assertIsInstance(result, str)
        self.assertIn("TestCo", result)
        self.assertIn("KEY SIGNALS", result)
        print("✓ Key signals retrieved successfully")
        print(f"Result length: {len(result)} characters")
    
    def test_04_nonexistent_company(self):
        """Test handling of non-existent company"""
        print("\n--- Test 4: Non-existent Company ---")
        result = self.tools.get_company_profile("NonexistentCompany")
        
        # Should return "no results" message
        self.assertIn("No", result)
        print("✓ Correctly handled non-existent company")
        print(f"Message: {result}")
    
    def test_05_date_filtering(self):
        """Test date filtering functionality"""
        print("\n--- Test 5: Date Filtering ---")
        
        # Test with very short timeframe (should find nothing or only very recent)
        result_short = self.tools.get_recent_news("TestCo", days=1)
        print(f"1-day lookback result length: {len(result_short)}")
        
        # Test with longer timeframe (should find more)
        result_long = self.tools.get_recent_news("TestCo", days=30)
        print(f"30-day lookback result length: {len(result_long)}")
        
        # Longer timeframe should return more or equal results
        self.assertGreaterEqual(len(result_long), len(result_short))
        print("✓ Date filtering working correctly")
    
    def test_06_result_formatting(self):
        """Test result formatting includes required elements"""
        print("\n--- Test 6: Result Formatting ---")
        result = self.tools.get_company_profile("TestCo")
        
        # Check for formatting elements
        required_elements = [
            "Result",  # Should have result markers
            "Content:",  # Should show content
            "Source Information:",  # Should show sources
        ]
        
        for element in required_elements:
            self.assertIn(element, result, f"Missing element: {element}")
            print(f"✓ Found: {element}")
        
        print("✓ Result formatting is correct")
    
    def test_07_langchain_tools_creation(self):
        """Test creation of LangChain tools"""
        print("\n--- Test 7: LangChain Tools Creation ---")
        tools = self.tools.get_langchain_tools()
        
        # Should return 3 tools
        self.assertEqual(len(tools), 3)
        print(f"✓ Created {len(tools)} tools")
        
        # Check tool names
        tool_names = [tool.name for tool in tools]
        expected_names = ["get_company_profile", "get_recent_news", "get_key_signals"]
        for name in expected_names:
            self.assertIn(name, tool_names)
            print(f"✓ Found tool: {name}")
        
        # Check tool descriptions exist
        for tool in tools:
            self.assertTrue(len(tool.description) > 0)
            print(f"  {tool.name}: {tool.description[:60]}...")
    
    def test_08_structured_tools_creation(self):
        """Test creation of structured tools with Pydantic schemas"""
        print("\n--- Test 8: Structured Tools Creation ---")
        tools = create_structured_tools(
            chroma_client=self.client,
            collection_name="test_company_documents"
        )
        
        # Should return 3 structured tools
        self.assertEqual(len(tools), 3)
        print(f"✓ Created {len(tools)} structured tools")
        
        # Check that tools have args_schema
        for tool in tools:
            self.assertIsNotNone(tool.args_schema)
            print(f"✓ {tool.name} has Pydantic schema")
    
    def test_09_tool_execution(self):
        """Test actual tool execution through LangChain interface"""
        print("\n--- Test 9: Tool Execution ---")
        tools = self.tools.get_langchain_tools()
        
        # Get the profile tool
        profile_tool = [t for t in tools if t.name == "get_company_profile"][0]
        
        # Execute the tool
        result = profile_tool.run("TestCo")
        
        self.assertIsInstance(result, str)
        self.assertIn("TestCo", result)
        print("✓ Tool executed successfully through LangChain interface")
    
    def test_10_metadata_filtering(self):
        """Test that metadata filtering works correctly"""
        print("\n--- Test 10: Metadata Filtering ---")
        
        # Test that profile query only returns profiles
        profile_result = self.tools.get_company_profile("TestCo")
        self.assertIn("profile", profile_result.lower())
        print("✓ Profile filter working")
        
        # Test that news query only returns news
        news_result = self.tools.get_recent_news("TestCo", days=30)
        self.assertIn("news", news_result.lower())
        print("✓ News filter working")
        
        # Test that signals query only returns signals
        signals_result = self.tools.get_key_signals("TestCo")
        self.assertIn("signal", signals_result.lower())
        print("✓ Signals filter working")
    
    def test_11_error_handling(self):
        """Test error handling for edge cases"""
        print("\n--- Test 11: Error Handling ---")
        
        # Test with empty string
        try:
            result = self.tools.get_company_profile("")
            # Should either handle gracefully or return error message
            self.assertIsInstance(result, str)
            print("✓ Handled empty string input")
        except Exception as e:
            print(f"✓ Raised exception for empty string: {type(e).__name__}")
        
        # Test with very large days value
        result = self.tools.get_recent_news("TestCo", days=10000)
        self.assertIsInstance(result, str)
        print("✓ Handled extreme date range")
    
    def test_12_source_attribution(self):
        """Test that results include proper source attribution"""
        print("\n--- Test 12: Source Attribution ---")
        result = self.tools.get_company_profile("TestCo")
        
        # Should include source information
        required_source_fields = ["document_type", "company_name", "source"]
        
        for field in required_source_fields:
            self.assertIn(field, result)
            print(f"✓ Includes source field: {field}")
        
        print("✓ Source attribution is complete")


class TestIntegration(unittest.TestCase):
    """Integration tests requiring LangChain agent (optional)"""
    
    def setUp(self):
        """Check if we can run integration tests"""
        try:
            from langchain.agents import initialize_agent
            from langchain_openai import ChatOpenAI
            import os
            
            if not os.getenv("OPENAI_API_KEY"):
                self.skipTest("OPENAI_API_KEY not set - skipping integration tests")
            
            self.can_run = True
        except ImportError:
            self.skipTest("LangChain or OpenAI not installed - skipping integration tests")
    
    def test_agent_integration(self):
        """Test full agent integration (requires API key)"""
        print("\n--- Integration Test: Agent ---")
        from langchain.agents import initialize_agent, AgentType
        from langchain_openai import ChatOpenAI
        
        # Set up tools
        client = chromadb.Client()
        collection = client.get_or_create_collection(name="test_integration")
        
        # Add sample data
        collection.add(
            ids=["int_test_1"],
            documents=["IntegrationCo is a test company for integration testing."],
            metadatas=[{
                "document_type": "profile",
                "company_name": "IntegrationCo",
                "source": "Test"
            }]
        )
        
        tools_obj = MeetingBriefingTools(
            chroma_client=client,
            collection_name="test_integration"
        )
        tools = tools_obj.get_langchain_tools()
        
        # Create agent
        llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0)
        agent = initialize_agent(
            tools=tools,
            llm=llm,
            agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
            verbose=False
        )
        
        # Test agent
        response = agent.run("Tell me about IntegrationCo")
        
        self.assertIsInstance(response, str)
        self.assertTrue(len(response) > 0)
        print("✓ Agent integration successful")
        print(f"Response preview: {response[:100]}...")


def run_all_tests():
    """Run all tests and display results"""
    print("\n" + "="*80)
    print("MEETING BRIEFING TOOLS - TEST SUITE")
    print("="*80)
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add core tests
    suite.addTests(loader.loadTestsFromTestCase(TestMeetingBriefingTools))
    
    # Add integration tests (will skip if dependencies missing)
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED!")
    else:
        print("\n❌ SOME TESTS FAILED")
    
    return result


if __name__ == "__main__":
    result = run_all_tests()
    exit(0 if result.wasSuccessful() else 1)
