# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Buffalo is a browser automation agent that uses AI to interact with web pages. It combines browser-use library with Gemini LLM to perform automated web browsing tasks.

## Development Commands

### Package Management
```bash
# Install dependencies
uv sync

# Add new dependencies
uv add <package-name>

# Add development dependencies
uv add --dev <package-name>

# Update dependencies
uv lock --upgrade
```

### Running the Application
```bash
# Run the main script
uv run python main.py

# Or activate virtual environment and run
source .venv/bin/activate  # On Linux/Mac
python main.py
```

## Architecture

### Core Components

**main.py**: Entry point that connects to Coral server and executes browser tests
- Receives test requests from other agents via Coral
- Uses Google Gemini for browser automation intelligence
- Reports results back through Coral messaging

**browser_tools.py**: Browser automation tools
- `execute_browser_task`: Executes single test prompts on websites
- `execute_browser_tasks_batch`: Runs multiple tests in parallel
- `get_pending_tasks`: Fetches tasks from Buffalo AI backend

### Dependencies

- **langchain**: Agent framework with tool calling capabilities
- **langchain-google-genai**: Google Gemini integration for LLM
- **langchain-mcp-adapters**: MCP client for Coral communication
- **browser-use**: Browser automation framework
- **aiohttp**: HTTP client for REST API calls

### Environment Setup

Requires a `.env` file with:
- `GEMINI_API_KEY`: Google Gemini API key for browser automation
- `CORAL_SSE_URL`: Coral server URL for agent communication
- `CORAL_AGENT_ID`: Agent identifier (default: buffalo)
- `BUFFALO_API_URL`: Buffalo AI backend URL for task management

## Key Implementation Notes

- The agent runs asynchronously using `asyncio`
- Executes browser test tasks delegated by the Buffalo AI backend
- Each task is a test prompt that gets executed on a specific website
- Results are automatically reported back to the backend via REST API
- Browser automation uses Gemini to intelligently navigate and test websites