import traceback
from dotenv import load_dotenv
import asyncio
from langchain.prompts import ChatPromptTemplate
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_mcp_adapters.client import MultiServerMCPClient

import os
import json
import urllib.parse
from qa_tools import buffalo_tools  # Import our browser automation tools
from configs import model

load_dotenv()

def get_tools_description(tools):
    return "\n".join(
        f"Tool: {tool.name}, Schema: {json.dumps(tool.args).replace('{', '{{').replace('}', '}}')}"
        for tool in tools
    )

messages = []

async def create_agent(coral_tools, agent_tools):
    coral_tools_description = get_tools_description(coral_tools)
    agent_tools_description = get_tools_description(agent_tools)
    combined_tools = coral_tools + agent_tools
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            f"""You are Buffalo, a specialized browser automation agent that executes test sessions for web applications through using browser use agents.

            # Your capabilities:
            1. Start test session (start_test_session) - Execute tests in batches with parallel browser automation given a website URL, mode can be "exploratory", "user-defined", or "buffalo-defined"
            2. Results (analyze_test_session) - Get the results of the test session

            # Instructions:
            1. Call wait_for_mentions from coral tools (timeoutMs: 30000) to receive test requests from other agents.
            2. When you receive a mention, keep the thread ID and the sender ID.
            3. If you are asked to run a test on a website
            - If you were not provided a test session id, generate a test session id using the `generate_test_session` tool, and send that test session id back to the requestor first and ask them to view the progress at buffalos.ai websitebefore proceeding to the next step
            4. execute the based on the mode of the test session defined below, generate a test session if not provided
            5. Use `send_message` from coral tools to send the results back to the sender.
            6. If any error occurs, send a detailed error message explaining what went wrong.
            7. Always respond back to the sender agent with actionable results.
            8. Wait for 2 seconds and repeat the process from step 1.
            
            # Inputs:
            Users can provide
            - a website URL
            - a test session id (optional) (please call the `generate_test_session` tool if not provided)
            - a list of modes
            - a project id (optional)
            - a email (optional)

            # Tools:
            - generate_test_session: Generate a test session for a website using this tool (call this if test session is not provided, you must use this tool to generate the test session, do not generate yourself)
            - start_test_session: Starts running tests in batches with parallel browser automation given a website URL, mode can be "exploratory", "user-defined", or "buffalo-preprod-checks", if not provided, the default mode is "exploratory", you don't need to ask for clarification
            - analyze_test_session: Generate a structured test
            - write_todos: Write todos to a help you keep track of your tasks, you can rewrite it to check off the tasks as you complete them

            # Test Modes:
            ## Exploratory Testing Workflow Mode:
            1) Call the `start_test_session` tool with (mode: "exploratory") to start a test session for the website, put the starting points in the unique_page_urls parameter.
            2) Call the `analyze_test_session` tool to generate a structured test report from the completed session, it will return a url to the report
            3) Share the url of the report to the Email agent and ask it to send a copy of the generated report to the user
            4) Report back to the user interface agent that you have completed the task
            
            ## User Defined Testing Workflow Mode:
            These are custom tests users have defined in their website (only available if project id is provided)
            1) Call the `start_test_session` tool with (mode: "user-defined") to start a test session for the website, you may leave the unique_page_urls empty.
            Rest of the workflow is the same as the exploratory test website workflow.

            ## Buffalo Preprod Checks Testing Workflow Mode:
            These are production readiness checks that are predefined by Buffalo AI
            1) Call the `start_test_session` tool with (mode: "buffalo-preprod-checks") to start a test session for the website, you may leave the unique_page_urls empty.
            Rest of the workflow is the same as the exploratory test website workflow.
            
            These are the list of coral tools: {coral_tools_description}
            These are the list of your testing tools: {agent_tools_description}"""
                ),
                ("placeholder", "{agent_scratchpad}")

    ])

    agent = create_tool_calling_agent(model, combined_tools, prompt)
    return AgentExecutor(agent=agent, tools=combined_tools, verbose=True, handle_parsing_errors=True)

async def main():

    runtime = os.getenv("CORAL_ORCHESTRATION_RUNTIME", None)
    if runtime is None:
        load_dotenv()

    base_url = os.getenv("CORAL_CONNECTION_URL")
    agentID = os.getenv("CORAL_AGENT_ID")

    coral_params = {
        "agentId": agentID,
        "agentDescription": "Buffalo - A testing agent that validates web apps using browser automation"
    }

    query_string = urllib.parse.urlencode(coral_params)

    CORAL_SERVER_URL = f"{base_url}?{query_string}"
    print(f"Connecting to Coral Server: {CORAL_SERVER_URL}")

    timeout = float(os.getenv("TIMEOUT_MS", "300"))
    client = MultiServerMCPClient(
        connections={
            "coral": {
                "transport": "sse",
                "url": CORAL_SERVER_URL,
                "timeout": timeout,
                "sse_read_timeout": timeout,
            }
        }
    )

    print("Multi Server Connection Established")

    coral_tools = await client.get_tools(server_name="coral")

    # Combine Buffalo's custom tools with Coral tools
    agent_tools = buffalo_tools  # Use our custom browser automation tools

    print(f"Coral tools count: {len(coral_tools)} and Buffalo tools count: {len(agent_tools)}")

    agent_executor = await create_agent(coral_tools, agent_tools)

    while True:
        try:
            print("Starting new agent invocation")
            await agent_executor.ainvoke({"agent_scratchpad": []})
            print("Completed agent invocation, restarting loop")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"Error in agent loop: {str(e)}")
            print(traceback.format_exc())
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
