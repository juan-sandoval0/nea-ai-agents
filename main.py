"""
Demo LangGraph agent for NEA AI Agents project.
This is a simple "hello world" agent to verify setup.
"""

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import HumanMessage, SystemMessage

# Load environment variables
load_dotenv()


def search_companies(query: str) -> str:
    """Search for companies in the portfolio (placeholder).

    Args:
        query: Search query for companies

    Returns:
        Placeholder company data
    """
    return f"Found 3 companies matching '{query}':\n1. TechStartup AI - Series A, $10M raised\n2. DataCo - Seed, $2M raised\n3. CloudSys - Series B, $25M raised"


def call_model(state: MessagesState):
    """Call the LLM with the current state."""
    messages = state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


# Initialize LLM with tools
llm = ChatOpenAI(model="gpt-4o", temperature=0)
tools = [search_companies]
llm_with_tools = llm.bind_tools(tools)

# Create the graph
workflow = StateGraph(MessagesState)

# Add nodes
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(tools))

# Add edges
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", tools_condition)
workflow.add_edge("tools", "agent")

# Compile the graph
app = workflow.compile()


def main():
    """Run the demo agent."""
    print("NEA AI Agents - Demo\n" + "=" * 50)

    # Create a sample query
    messages = [
        SystemMessage(content="You are a helpful AI assistant for venture capital workflows. Use the available tools to answer questions."),
        HumanMessage(content="What companies do we have in AI?")
    ]

    print("\nUser: What companies do we have in AI?\n")
    print("Agent response:")
    print("-" * 50)

    # Invoke the agent
    result = app.invoke({"messages": messages})

    # Print the final response
    final_message = result["messages"][-1]
    print(final_message.content)
    print("\n" + "=" * 50)
    print("Demo complete! Setup is working correctly.")


if __name__ == "__main__":
    main()
