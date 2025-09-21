### Buffalo Agent

A LangChain-based browser QA agent that can crawl a site, generate concrete UI tests, and execute them in parallel using lightweight browser workers. It exposes two tools for orchestration and reporting.

### Key capabilities
- Exploratory testing: Scout a page to inventory interactive elements, synthesize 6–8 precise test tasks, then execute them.
- User flow testing: Execute predefined, site-specific flows (from Convex `tests` table) in batches.
- Production checks: Run checklist-style smoke tests.
- Parallel execution: A configurable worker pool launches multiple browser agents concurrently.
- Result reporting: Summarized results include per-task status and duration; intended to be shared back to other agents or users.

### Tools
- start_test_session
  - Launches a test run. Creates a test session in Convex and executes one or more modes.
  - Signature:
    - base_url: string – website to test
    - unique_page_urls: string[] – representative starting URLs (exploratory); can be empty for user_flow
    - num_agents: number – parallel workers (default 3)
    - headless: boolean – browser headless mode (default false)
    - mode: "exploratory" | "user_flow" | "prod_checks" | "all" (default "all")
  - Behavior:
    - exploratory: for each `unique_page_urls`, scout the page to generate specific element-focused tasks, then execute via the pool
    - user_flow: fetch site-specific flows from Convex and execute
    - prod_checks: fetch checklist tests from Convex and execute
    - all: run exploratory + user_flow + prod_checks

- analyze_test_session
  - Produces a consolidated report for a given `test_id`, including formatted duration.

### How it works
- Scouting (exploratory): `scout_page(url)` navigates headlessly and inventories interactive elements. It then prompts an LLM to partition findings into a JSON array of very specific test tasks that always begin with navigation instructions. If parsing fails, sensible fallback tasks are used.
- Pool runner: `run_pool(tasks, base_url, num_agents, headless)` assigns one task per worker in a bounded parallel semaphore. Each worker spins up a small `browser_use` Agent session, executes the task, captures final result text, and tears down the browser session. Results are stored in `_test_results[test_id]` along with timing metadata.

### Run modes
- Exploratory: call `start_test_session(..., mode="exploratory")` with `unique_page_urls` representing one URL per page-type (normalized upstream). The agent scouts and generates concrete task lists before executing them.
- User Flow: call with `mode="user_flow"` and the agent retrieves `websiteSpecific` flows from Convex.
- Prod Checks: call with `mode="prod_checks"` and the agent retrieves `checklist` items from Convex.
- All: runs all three in sequence.

### Quick start

#### Docker (Recommended)

The easiest way to run Buffalo is using Docker, which handles all browser dependencies automatically:

1. **Setup environment variables:**
   ```bash
   cp coral-server/agents/buffalo/env.example .env
   # Edit .env with your API keys and configuration
   ```

2. **Build and run with Docker Compose:**
   ```bash
   docker-compose up --build
   ```

3. **Or build and run manually:**
   ```bash
   # Build the image
   docker build -t buffalo-agent .
   
   # Run the container
   docker run --env-file .env \
     --shm-size=2g \
     --security-opt seccomp:unconfined \
     buffalo-agent
   ```

#### Local Development

Environment variables (mirror `.env.example`):
- `CORAL_SSE_URL` - Coral SSE endpoint
- `CORAL_AGENT_ID` - Agent identifier
- `CORAL_ORCHESTRATION_RUNTIME` - Orchestration runtime (optional)
- `TIMEOUT_MS` - Connection/tool timeout (default 300)
- `GOOGLE_API_KEY` - For Gemini LLM
- `OPENAI_API_KEY` - For OpenAI models (optional)
- `FIRECRAWL_API_KEY` - For web crawling (optional)
- `BROWSER_USE_MODEL` - Browser automation model (default: gemini-2.0-flash-exp)
- `CONVEX_URL` - Convex deployment URL
- `CONVEX_DEPLOY_KEY` - Convex deploy key

**Note:** Docker is recommended as it automatically installs Playwright browsers and handles all system dependencies.

### CLI scripts

- `agents/buffalo/buffalo_standalone.py`: interactive loop using the LangChain agent. Accepts input and calls tools.

Examples:
```bash
# Scout a URL and view suggested tasks
python agents/buffalo/test_agent_standalone.py scout --url https://example.com

# Run a pool with 5 workers headless using tasks from a JSON file
python agents/buffalo/test_agent_standalone.py run-pool \
  --base-url https://example.com \
  --tasks-file tasks.json \
  --num-agents 5 \
  --headless
```

### Additional CLI: `vibe-test-cli.py`

- Thin CLI to call the underlying async functions directly: `scout_page` and `run_pool`.
- Commands:
  - `scout`: inventory a URL and print or save the generated tasks JSON
  - `run-pool`: execute tasks against a base URL with a worker pool
  - `explore`: chain `scout` → `run-pool` in one command
- Common flags:
  - `--num-agents`: number of parallel workers (default 3)
  - `--headless`: run browsers headless
  - `--tag`: optional label for the run
  - `--tasks` or `--tasks-file`: provide tasks as a JSON array string or a path to a JSON file
  - `--out` / `--tasks-out`: write tasks JSON to a file

Usage examples:
```bash
# Scout a URL and save suggested tasks to a file
python agents/buffalo/vibe-test-cli.py scout \
  --url https://example.com \
  --out tasks.json

# Run a pool with 5 workers headless using tasks from a file
python agents/buffalo/vibe-test-cli.py run-pool \
  --base-url https://example.com \
  --tasks-file tasks.json \
  --num-agents 5 \
  --headless \
  --tag prod_checks

# Run a pool with inline JSON tasks
python agents/buffalo/vibe-test-cli.py run-pool \
  --base-url https://example.com \
  --tasks '["Navigate to https://example.com using go_to_url, then test the header nav - click on Home", "Navigate to https://example.com using go_to_url, then submit the search form with query 'test'"]'

# One-shot explore: scout then immediately run the pool; save generated tasks
python agents/buffalo/vibe-test-cli.py explore \
  --url https://example.com \
  --num-agents 3 \
  --headless \
  --tag exploratory \
  --tasks-out tasks.json
```

#### Coral orchestration (agent-to-agent)
- Configure `CORAL_CONNECTION_URL`, `CORAL_AGENT_ID`, and run:
  ```bash
  python agents/buffalo/main.py
  ```
- Buffalo will wait for mentions, execute a test session, then send results back.

Programmatic usage examples
---------------------------
Within a LangChain agent, these tools are already registered as `buffalo_tools`.

Start exploratory test session:
```python
from agents.buffalo.qa_tools import start_test_session

test_id_msg = await start_test_session(
    base_url="https://example.com",
    unique_page_urls=[
        "https://example.com/",
        "https://example.com/products/123",
        "https://example.com/cart",
    ],
    num_agents=5,
    headless=True,
    mode="exploratory",
)
```

Analyze results:
```python
from agents.buffalo.qa_tools import analyze_test_session

summary = await analyze_test_session(test_id="<id-from-start>")
```

Notes
-----
- Worker caps: the pool bounds concurrency with a semaphore; practical upper bounds depend on system resources.
- Windows and viewports are minimized and tiled in non-headless mode for visibility.
- If the scout partitioning response isn’t valid JSON, deterministic fallback task sets are used.