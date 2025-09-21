import traceback
from dotenv import load_dotenv
import asyncio
from langchain.prompts import ChatPromptTemplate
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.messages import HumanMessage
import json
from qa_tools import buffalo_tools  # Import our browser automation tools
from configs import model

load_dotenv()

def get_tools_description(tools):
    return "\n".join(
        f"Tool: {tool.name}, Schema: {json.dumps(tool.args).replace('{', '{{').replace('}', '}}')}"
        for tool in tools
    )

async def create_agent(agent_tools):
    agent_tools_description = get_tools_description(agent_tools)
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            f"""You are Buffalo, a specialized browser automation agent that executes test sessions for web applications through using browser use agents.

            # Your capabilities:
            1. Start test session (start_test_session) - Execute tests in batches with parallel browser automation given a website URL, mode can be "exploratory", "user-defined", or "buffalo-defined"
            2. Results (analyze_test_session) - Get the results of the test session
            3. Write todos (write_todos) - Write todos to a help you keep track of your tasks, you can rewrite it to check off the tasks as you complete them
            4. Generate test session (generate_test_session) - Generate a test session for a website using this tool (call this if test session is not provided, you must use this tool to generate the test session, do not generate yourself)

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
            
            These are the list of your testing tools: {agent_tools_description}"""
                ),
                ("user", "{input}"),
                ("placeholder", "{agent_scratchpad}")
    ])

    agent = create_tool_calling_agent(model, agent_tools, prompt)
    return AgentExecutor(agent=agent, tools=agent_tools, verbose=True, handle_parsing_errors=True)

async def main():
    agent_tools = buffalo_tools  # Use our custom browser automation tools
    print(f"Buffalo tools count: {len(agent_tools)}")

    agent_executor = await create_agent(agent_tools)

    while True:
        try:
            input_data = input("User: ")
            print("Starting new agent invocation")
            await agent_executor.ainvoke({"input": input_data})
            print("Completed agent invocation, restarting loop")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"Error in agent loop: {str(e)}")
            print(traceback.format_exc())
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
