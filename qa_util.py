"""
Browser automation tools for Buffalo agent

# Feature 1: Crawl Testing Workflow

1. Start with a seed URL
2. Scout page: Use a browser task to identify top 5 interactive elements on the page, and create a list of specific testing tasks, what to expect for the next image
3. Execute tasks in parallel, checking if next image matches expectations
4. Report results, log success/failure of elements by page of the website
5. If we are on a new page, call the scout page function again and come up with new test tasks with expectations
6. Repeat until we have scanned the entire website

Notes:
- We should use iterative BFS with a task queue, each task is a tuple of (url, task, expected output)
- Browser workers, we only have 5 workers so we should pop the top 5 tasks at each iteration, one task per browser agent
- Browser agents could takes in an instruction to first navigate to the url, then execute the task, then reason if the next image matches the expectations
- Browser agents should result in an output schema of (success: bool, comment: str) and save the tests into the database with the (url, task, success, comment)

# Feature 2: Specified User Flow Testing

1. Given a list of user flow tasks (user defined), see if we can fully execute them
2. Execute the tasks in parallel, one task per browser agent
3. While executing the task, let the agent note down its difficulties
4. Stop when bug found or task complete
"""

import logging
import base64
from textwrap import dedent
import time
import asyncio
from typing import List, Optional, Literal
from browser_use import Agent, BrowserProfile, BrowserSession
from browser_use.browser.views import BrowserStateSummary
from pydantic import BaseModel, Field
import requests

from custom_types import Task, UniqueUrls, TestingTaskList
from configs import convex_client, get_screen_dimensions, model, browser_llm, firecrawl_client
logger = logging.getLogger(__name__)

class TestExecutionResult(BaseModel):
    is_working: bool
    message: str
    error: Optional[str]

# ---- Logging helpers ----
def _truncate(text: str, max_len: int = 2000) -> str:
    try:
        if text is None:
            return ""
        s = str(text)
        return s if len(s) <= max_len else s[:max_len] + "… [truncated]"
    except Exception:
        return "[unserializable]"

def _extract_final_result_text(history) -> str:
    try:
        final_attr = getattr(history, "final_result", None)
        if callable(final_attr):
            return str(final_attr())
        if final_attr is not None:
            return str(final_attr)
        return str(history)
    except Exception as e:
        logger.exception("Failed extracting final result from history: %s", e)
        return str(history)

async def run_prod_checks(base_url: str, prod_checks: List[Task], num_agents: int = 3, headless: bool = False, test_session_id: str = None, sensitive_info: dict | None = None):
    """
    QA check prod checks orchestrator, process tasks in batches
    """
    convex_client.mutation("testSessions:addMessageToTestSession", {
        "testSessionId": test_session_id,
        "message": f"Running {len(prod_checks)} prod checks"
    })
    await run_pool(prod_checks, base_url, num_agents, headless, tag="preprod_checks", test_session_id=test_session_id, sensitive_info=sensitive_info)
    convex_client.mutation("testSessions:addMessageToTestSession", {
        "testSessionId": test_session_id,
        "message": f"Completed {len(prod_checks)} prod checks"
    })

async def run_user_flow_testing(base_url: str, user_flow_tasks: List[Task], num_agents: int = 3, headless: bool = False, test_session_id: str = None, sensitive_info: dict | None = None):
    """
    QA check user flow tasks orchestrator, process tasks in batches
    """
    convex_client.mutation("testSessions:addMessageToTestSession", {
        "testSessionId": test_session_id,
        "message": f"Running {len(user_flow_tasks)} user flow tasks"
    })
    await run_pool(user_flow_tasks, base_url, num_agents, headless, tag="user_flow", test_session_id=test_session_id, sensitive_info=sensitive_info)
    convex_client.mutation("testSessions:addMessageToTestSession", {
        "testSessionId": test_session_id,
        "message": f"Completed {len(user_flow_tasks)} user flow tasks"
    })

async def generate_sitemap(base_url: str, test_session_id: str | None = None) -> list:
    """Generate a sitemap for a website"""
    try:
        if test_session_id:
            convex_client.mutation("testSessions:addMessageToTestSession", {
                "testSessionId": test_session_id,
                "message": f"Starting sitemap generation for {base_url}"
            })
    except Exception:
        pass

    res = firecrawl_client.map(url=base_url, limit=35)
    try:
        if test_session_id:
            convex_client.mutation("testSessions:addMessageToTestSession", {
                "testSessionId": test_session_id,
                "message": "Raw sitemap fetched, normalizing URLs"
            })
    except Exception:
        pass

    # Get all the unique urls from the sitemap
    prompt = f"""
    Generate a sitemap from the website URL, then normalize paths by stripping query params and collapsing dynamic segments (e.g., treat /product/123 and /product/456 as the same type). For each type, select one representative URL (e.g., keep /product/123, drop the rest), it should return you a bunch of starting points within the website to test

    Limit to the top 3 most unique and representative starting points urls

    Return an array of starting points
    Sitemap:
    {res}
    """
    response: UniqueUrls = await model.with_structured_output(UniqueUrls).ainvoke(prompt)
    try:
        if test_session_id:
            convex_client.mutation("testSessions:addMessageToTestSession", {
                "testSessionId": test_session_id,
                "message": f"Selected {len(response.urls)} unique starting URLs"
            })
    except Exception:
        pass
    return response.urls
    
async def run_exploratory_testing(base_url: str, num_agents: int = 3, headless: bool = False, test_session_id: str = None, sensitive_info: dict | None = None):
    """
    QA check websites orchestrator, it will:
    1. Get a sitemap of the base url
    2. Loop through each starting URL
    3. Call the run_pool function to test the website
    4. Return the results
    
    Args:
        starting_urls: List of starting URLs to test, these should be the starting points within a website to test
    """

    convex_client.mutation("testSessions:addMessageToTestSession", {
        "testSessionId": test_session_id,
        "message": f"Generating sitemap for {base_url}"
    })

    starting_urls = await generate_sitemap(base_url, test_session_id=test_session_id)

    convex_client.mutation("testSessions:addMessageToTestSession", {
            "testSessionId": test_session_id,
            "message": f"Crawled {len(starting_urls)} starting URLs"
        })

    existing_tasks = []
    for starting_url in starting_urls:
        qa_tasks = await scout_page(starting_url, existing_tasks=existing_tasks, test_session_id=test_session_id, sensitive_info=sensitive_info)

        convex_client.mutation("testSessions:addMessageToTestSession", {
            "testSessionId": test_session_id,
            "message": f"Scouted {starting_url} and found {len(qa_tasks)} tasks"
        })

        await run_pool(qa_tasks, starting_url, num_agents, headless, tag="exploratory", test_session_id=test_session_id, sensitive_info=sensitive_info)

        convex_client.mutation("testSessions:addMessageToTestSession", {
            "testSessionId": test_session_id,
            "message": f"Completed {len(qa_tasks)} exploratory tasks for {starting_url}"
        })
    
    convex_client.mutation("testSessions:addMessageToTestSession", {
        "testSessionId": test_session_id,
        "message": f"Completed exploratory testing"
    })

async def run_pool(tasks: List[Task], base_url: str, num_agents: int = 3, headless: bool = False, tag: str | None = None, test_session_id: str = None, sensitive_info: dict | None = None) -> str:
    start_time = time.time()

    task_execution_ids = []

    if sensitive_info is not None:
        logger.info(f"Sensitive info: {sensitive_info}")

    try:
        convex_client.mutation("testSessions:addMessageToTestSession", {
            "testSessionId": test_session_id,
            "message": f"Creating {len(tasks)} test executions for {tag or 'general'} on {base_url}"
        })
    except Exception:
        pass

    # Add a test execution for each qa_task
    for task in tasks:
        task_execution_id = convex_client.mutation("testExecutions:createTestExecution", {
            "testSessionId": test_session_id,
            "name": task.name,
            "prompt": task.prompt,
            "type": tag,
            "websiteUrl": base_url
        })
        task_execution_ids.append(task_execution_id)
        logger.debug("Created test execution id=%s for task='%s'", task_execution_id, task)

    browser_agent_system_prompt = dedent(f"""
        You are a browser automation agent that executes a single test task.
        You will be given a task description and a website URL.
        You will need to execute the task on the website.

        ### Dealing with login pages
        If you encounter a login page, you should have login details in the sensitive data if they are provided, otherwise just fail the test and say that you need login details.
        
        ## QA Agent Self-Check Questions

        ### Clarity of Test
        - Am I **specific enough**? (Each step references exact elements or actions, not vague goals)
        - Did I **name actions directly** (e.g. `click_element`, `extract_structured_data`) instead of open-ended instructions?

        ### Execution Validity
        - Did I **navigate to the correct page/URL**?
        - Was the **target element found and interactable** (visible, enabled, not hidden)?
        - If direct click fails, did I try a **keyboard navigation fallback** (`send_keys`)?

        ### Outcome Expectations
        - Did the **expected success outcome** occur (URL/route, DOM update, toast, API 2xx)?
        - If not, was there a **clear failure outcome** (error message, validation, 4xx/5xx)?
        - If neither, is the result **ambiguous** and should I warn?

        ### Robustness & Recovery
        - Did I attempt **error recovery** (retry navigation, refresh, go_back, alternate path) before failing?
        - For flows with custom actions (e.g. 2FA), did I call the **correct integration** instead of hacking around?

        ### Evidence
        - Did I capture **proof** (screenshot, console errors, key network logs)?
        - Could another tester understand the **issue from my output alone**?

        ### Warnings
        - Should I warn about:
        - **Blockers** (auth walls, missing element, infinite spinner)?
        - **Flakiness** (passes only after retries, unstable selectors)?
        - **Gaps** (no oracle, missing test data, unclear outcome)?
    """)

    async def run_single_agent(i: int):
        task_description = f"\n\nTask to test:\n{tasks[i].prompt}"

        # Update the task execution status to running
        convex_client.mutation("testExecutions:updateTestExecutionStatus", {
            "testExecutionId": task_execution_ids[i],
            "status": "running"
        })
        
        try:
            # browser configuration with optimizations for faster startup
            browser_args = [
                '--disable-gpu', 
                '--no-sandbox', 
                '--disable-dev-shm-usage',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-features=TranslateUI',
                '--disable-component-extensions-with-background-pages',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-background-networking'
            ]
            if headless:
                browser_args.append('--headless=new')
            
            window_config = {}
            
            if not headless:
                # window positioning for non-headless mode
                screen_width, screen_height = get_screen_dimensions()
                
                # Use a typical desktop browser size while respecting available screen space
                window_width = min(1280, max(800, screen_width - 40))
                window_height = min(800, max(600, screen_height - 80))
                viewport_width = window_width
                viewport_height = max(600, window_height - 80)
                
                margin = 10
                spacing = 15
                
                usable_width = screen_width - (2 * margin)
                windows_per_row = max(1, usable_width // (window_width + spacing))
                
                row = i // windows_per_row
                col = i % windows_per_row
                
                x_offset = margin + col * (window_width + spacing)
                y_offset = margin + row * (window_height + spacing)
                
                if x_offset + window_width > screen_width:
                    x_offset = screen_width - window_width - margin
                if y_offset + window_height > screen_height:
                    y_offset = screen_height - window_height - margin
                
                window_config = {
                    "window_size": {"width": window_width, "height": window_height},
                    "viewport": {"width": viewport_width, "height": viewport_height}
                }
                # Note: window_position removed due to API incompatibility - expects width/height but needs x/y
            
            logger.debug("Agent %d configuring BrowserProfile. headless=%s, args=%s, window_config=%s", i, headless, browser_args, window_config)
            browser_profile = BrowserProfile(
                headless=headless,
                disable_security=True,
                user_data_dir=None,
                args=browser_args,
                ignore_default_args=['--enable-automation'],
                wait_for_network_idle_page_load_time=2.0,
                maximum_wait_page_load_time=15.0,
                wait_between_actions=0.4,
                **window_config
            )
            
            browser_session = BrowserSession(browser_profile=browser_profile, allowed_domains=[base_url])
            logger.debug("Agent %d BrowserSession created", i)
            
            try:
                def on_step(state: BrowserStateSummary, output, step_no):
                    # state is BrowserStateSummary
                    if not state.screenshot:
                        return

                    # 1) Decode base64 to PNG bytes
                    base64_bytes = base64.b64decode(state.screenshot)
                    print(f"Saving screenshot for step {step_no}")

                    # 2) Get upload URL from Convex (it's a mutation in your backend)
                    upload_url = convex_client.mutation("testExecutions:generateUploadUrl")

                    # 3) Upload bytes to Convex storage via HTTP
                    resp = requests.post(upload_url, data=base64_bytes, headers={"Content-Type": "image/png"})
                    resp.raise_for_status()
                    storage_id = resp.json()["storageId"]  # returned by Convex upload endpoint

                    # 4) Save screenshot reference on your test execution (mutation expects Id<'_storage'>)
                    convex_client.mutation(
                        "testExecutions:saveTestExecutionScreenshot",
                        {"testExecutionId": task_execution_ids[i], "storageId": storage_id},
                    )

                if sensitive_info is not None:
                    logger.info(f"Sensitive info: {sensitive_info}, Kenji will be able to login")
                else:
                    logger.info("No sensitive info provided, Kenji will not be able to login")

    
                agent = Agent(
                    extend_system_message=browser_agent_system_prompt,
                    task=task_description,
                    llm=browser_llm,
                    browser_session=browser_session,
                    use_vision=True,
                    sensitive_data=sensitive_info,
                    output_model_schema=TestExecutionResult,
                    register_new_step_callback=on_step
                )
                logger.info("Agent %d starting run for task_execution_id=%s", i, task_execution_ids[i])
                t0 = time.time()

                history = await agent.run()
                elapsed = time.time() - t0
                logger.info("Agent %d finished run in %.2fs", i, elapsed)
                logger.debug("Agent %d history (truncated): %s", i, _truncate(history))
                
                result_text = _extract_final_result_text(history)
                logger.debug("Agent %d final_result (truncated): %s", i, _truncate(result_text))

                validate_results_response = TestExecutionResult.model_validate_json(result_text)
                convex_client.mutation("testExecutions:saveTestExecutionResults", {
                    "testExecutionId": task_execution_ids[i],
                    "results": {
                        "passed": validate_results_response.is_working,
                        "message": validate_results_response.message,
                        "errorMessage": validate_results_response.error
                    }
                })
                
                return {
                    "agent_id": i,
                    "task": task_description,
                    "result": result_text,
                    "timestamp": time.time(),
                    "status": "success"
                }
            finally:
                # Properly close browser session to prevent lingering processes
                try:
                    await browser_session.aclose()
                    logger.debug("Agent %d BrowserSession closed", i)
                except Exception:
                    logger.exception("Agent %d error closing BrowserSession", i)
            
        except Exception as e:
            logger.exception("Error running agent %d: %s", i, e)
            try:
                convex_client.mutation("testExecutions:saveTestExecutionFailure", {
                    "testExecutionId": task_execution_ids[i],
                    "failure": {
                        "message": "Execution failed",
                        "errorMessage": str(e)
                    }
                })
            except Exception as persist_err:
                logger.exception("Failed to persist execution failure for agent %d: %s", i, persist_err)
            return {
                "agent_id": i,
                "task": task_description,
                "error": str(e),
                "timestamp": time.time(),
                "status": "error"
            }

    # run agents in parallel
    semaphore = asyncio.Semaphore(min(num_agents, 10))
    
    async def run_agent_with_semaphore(i: int):
        async with semaphore:
            return await run_single_agent(i)
    
    logger.info("Running %d tasks with up to %d concurrent agents for base_url=%s (headless=%s, tag=%s)", len(tasks), num_agents, base_url, headless, tag)
    try:
        convex_client.mutation("testSessions:addMessageToTestSession", {
            "testSessionId": test_session_id,
            "message": f"Running {len(tasks)} tasks with up to {num_agents} agents (headless={headless})"
        })
    except Exception:
        pass

    results = await asyncio.gather(
        *[run_agent_with_semaphore(i) for i in range(len(tasks))], 
        return_exceptions=True
    )
    success_count = 0
    error_count = 0
    for r in results:
        if isinstance(r, Exception):
            error_count += 1
            logger.exception("Agent raised exception: %s", r)
        elif isinstance(r, dict) and r.get("status") == "error":
            error_count += 1
            logger.error("Agent reported error: %s", r.get("error"))
        else:
            success_count += 1
    logger.info("Agents completed: success=%d, error=%d", success_count, error_count)
    try:
        convex_client.mutation("testSessions:addMessageToTestSession", {
            "testSessionId": test_session_id,
            "message": f"Completed batch: success={success_count}, error={error_count}"
        })
    except Exception:
        pass
    
    end_time = time.time()
    
    # Allow time for browser sessions to close gracefully
    await asyncio.sleep(1)
    
    # store results
    test_data = {
        "url": base_url,
        "agents": num_agents,
        "start_time": start_time,
        "end_time": end_time,
        "duration": end_time - start_time,
        "results": [r for r in results if not isinstance(r, Exception)],
        "status": "completed"
    }
    logger.info("run_pool completed for %s in %.2fs", base_url, test_data["duration"])
    return test_data

async def scout_page(base_url: str, existing_tasks: list[Task], test_session_id: str | None = None, sensitive_info: dict | None = None) -> list[Task]:
    """Scout agent that identifies all interactive elements on the page"""
    try:
        logger.info("Scout starting for base_url=%s", base_url)
        try:
            if test_session_id:
                convex_client.mutation("testSessions:addMessageToTestSession", {
                    "testSessionId": test_session_id,
                    "message": f"Scouting interactive elements on {base_url}"
                })
        except Exception:
            pass
        browser_profile = BrowserProfile(
            headless=True,
            disable_security=True,
            user_data_dir=None,
            args=[
                '--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage', '--headless=new',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-features=TranslateUI',
                '--disable-component-extensions-with-background-pages',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-background-networking'
            ],
            wait_for_network_idle_page_load_time=2.0,
            maximum_wait_page_load_time=15.0,
            wait_between_actions=0.4
        )
        
        browser_session = BrowserSession(browser_profile=browser_profile, allowed_domains=[base_url])
        logger.debug("Scout BrowserSession created")
        
        try:
            scout_task = f"""Navigate to {base_url} using the go_to_url action, then identify ALL interactive elements on the page. Do NOT click anything, just observe and catalog what's available. List buttons, links, forms, input fields, menus, dropdowns, and any other clickable elements you can see. Provide a comprehensive inventory, also note whether you need to login to test the page or not, please put a final variable saying login_required: True or False
            
            if there is a login page, then login first (you should have login details in the sensitive info if they are provided, do not identify interactive elements in the login page or any third party apps navigated from the main page, only generate interactive elements if there is core logic to the user's app)
            """
            
            agent = Agent(
                extend_system_message="""### Dealing with login pages
        Do not bother testing login or integration pages, just focus on the main website.
        If you need to login, you should have login details in the sensitive info if they are provided, otherwise just fail the test and say that you need login details.""",
                task=scout_task,
                llm=browser_llm,
                browser_session=browser_session,
                use_vision=True,
                sensitive_data=sensitive_info
            )
            logger.info("Scout agent starting run")
            t0 = time.time()
            history = await agent.run()
            elapsed = time.time() - t0
            logger.info("Scout agent finished run in %.2fs", elapsed)
            try:
                if test_session_id:
                    convex_client.mutation("testSessions:addMessageToTestSession", {
                        "testSessionId": test_session_id,
                        "message": "Scout completed, generating test cases"
                    })
            except Exception:
                pass
        finally:
            # Properly close scout browser session to prevent lingering processes
            try:
                await browser_session.aclose()
                logger.debug("Scout BrowserSession closed")
            except Exception:
                logger.exception("Scout error closing BrowserSession")
        
        scout_result = _extract_final_result_text(history)
        logger.debug("Scout final_result (truncated): %s", _truncate(scout_result))
        
        # partition elements with llm
        partition_prompt = dedent(f"""
            You are generating HIGH-VALUE browser tests from a scout report of interactive elements on {base_url}.

            Goal:
            Produce 4–6 NON-OVERLAPPING tasks that each:
            - Start with navigation to {base_url}
            - Target ONE specific element (high signal)
            - Name concrete ACTIONS to use (e.g., go_to_url, click_element_by_text, send_keys, extract_structured_data)
            - Define success/failure oracles
            - Avoid low-value tests (e.g., “can type in field”)
            - Don't bother testing 3rd party integrations, you can test if the app redirects properly but dont actually create tests on the third party app

            Scout report:
            {scout_result}

            Existing tasks to avoid duplicating:
            {existing_tasks}

            Rules:
            1) Prioritize end-to-end goals (navigate, submit, login) over trivial clicks.
            2) Be SPECIFIC about the element and provide a STABLE locator (prefer data-testid; else role+name; else exact text; avoid brittle CSS).
            3) State PRECONDITIONS (auth, seeded data). If login needed, include the login steps explicitly.
            4) Define ORACLES: route/URL change, DOM assertion, toast text, API status/method/path. No vague “should work”.
            5) Include ONE valuable NEGATIVE check (e.g., duplicate email shows “Email in use”).
            6) EXPLICIT WAITS by condition (element visible/enabled, network call settled). Avoid fixed sleeps unless recovery requires it.
            7) Deduplicate intents vs {existing_tasks}. If similar, pick a different element or path.

            Action usage guidelines (keep it concrete):
            - Name actions directly: e.g., use search_google, click_element_by_index, scroll, extract_structured_data, write_file, send_keys.
            - Keyboard fallback if clicking fails: use send_keys with sequences like "Tab Tab Enter" or "ArrowDown ArrowDown Enter".
            - Custom actions (if available): ALWAYS use them when relevant (e.g., get_2fa_code for 2FA). NEVER scrape 2FA codes from the page.
            - Error recovery: if navigation blocked by anti-bot/captcha, try search_google → open result; if timeout, use go_back and retry once, then warn.

            ### Login pages
            The scout report should mention whether you need to login to test the website or not, it has a variable called login_required: True or False
            If it is true, then you need to include a step in all your test cases to login first before navigating to the right page

            Output format (JSON array of compact tasks):
            {{
                "tasks": [
                    {{
                        "name": "Test [element intent/description]",
                        "prompt": "[If login true, then "First login to the website using the login details"] Navigate to {base_url} using go_to_url, then [named ACTION with exact target]. Expect SUCCESS: [specific oracle]. If click fails, use send_keys fallback. If page times out, go_back and retry once. Expect FAILURE: [specific error] if applicable."
                    }}
                ]
            }}

            Make each task VERY specific about which exact element to test and which ACTIONS to call. ALWAYS start with navigation.
        """)
        logger.info("Scout partitioning elements via LLM")
        partition_response: TestingTaskList = await model.with_structured_output(TestingTaskList).ainvoke(partition_prompt)
        logger.debug("Partition LLM raw response (truncated): %s", _truncate(partition_response))
        
        element_tasks = partition_response.tasks
        logger.info("Scout partitioned %d element tasks", len(element_tasks))
        try:
            if test_session_id:
                convex_client.mutation("testSessions:addMessageToTestSession", {
                    "testSessionId": test_session_id,
                    "message": f"Generated {len(element_tasks)} test cases for {base_url}"
                })
        except Exception:
            pass
        return element_tasks
        
    except Exception as e:
        # fallback tasks if scouting fails
        logger.exception("Scout failed for base_url=%s: %s", base_url, e)
        try:
            if test_session_id:
                convex_client.mutation("testSessions:addMessageToTestSession", {
                    "testSessionId": test_session_id,
                    "message": f"Scout failed for {base_url}, using fallback tasks"
                })
        except Exception:
            pass
        return [
            Task(
                name="Test navigation elements in the header area",
                prompt=f"Navigate to {base_url} using go_to_url, then test the navigation elements in the header area, expect [expected output]"
            ),
            Task(
                name="Test main content links and buttons",
                prompt=f"Navigate to {base_url} using go_to_url, then test the main content links and buttons, expect [expected output]"
            ),
            Task(
                name="Test footer links and elements",
                prompt=f"Navigate to {base_url} using go_to_url, then test the footer links and elements, expect [expected output]"
            ),
            Task(
                name="Test any form elements found",
                prompt=f"Navigate to {base_url} using go_to_url, then test the any form elements found, expect [expected output]"
            ),
            Task(
                name="Test sidebar or secondary navigation",
                prompt=f"Navigate to {base_url} using go_to_url, then test the sidebar or secondary navigation, expect [expected output]"
            ),
            Task(
                name="Test any remaining interactive elements",
                prompt=f"Navigate to {base_url} using go_to_url, then test the any remaining interactive elements, expect [expected output]"
            )
        ]

class Issue(BaseModel):
    """Represents a single issue found during testing."""
    severity: Literal["High", "Medium", "Low"] = Field(description="The severity of the issue.")
    risk: str = Field(description="What is the risk of this issue?")
    details: str = Field(description="Details about the issue that was found.")
    testExecutionId: str = Field(description="The ID of the test execution where this issue was found.")
    advice: str = Field(description="Advice on how to fix the issue.")

class ReportGenerator(BaseModel):
    """Always use this tool to structure your response to the user."""
    summary: str = Field(description="A summary of the test session.")
    issues: List[Issue] = Field(description="A list of issues found during the test session.")

async def summarize_test_session(test_session_id: str) -> str:
    """Summarize a test session"""
    test_executions = convex_client.query("testExecutions:getTestExecutionsBySessionId", {"testSessionId": test_session_id})

    prompt = f"""
    You are a QA engineer summarizing a test session.
    Based on the following test executions, generate a report.
    The report should include a summary and a list of issues.
    For each issue, provide the severity, risk, details, the test execution ID, and advice on how to fix it.
    Prioritize failed tests and tests with error messages.

    Test Executions:
    {test_executions}
    """
    response: ReportGenerator = await model.with_structured_output(ReportGenerator).ainvoke(prompt)
    
    # Convert Pydantic model to dictionary
    report_data = response.model_dump()
    
    try:
        convex_client.mutation("testSessions:addMessageToTestSession", {
            "testSessionId": test_session_id,
            "message": "Generating final report from test executions"
        })
    except Exception:
        pass

    convex_client.mutation(
        "testReports:createReport",
        {
            "testSessionId": test_session_id,
            "summary": report_data["summary"],
            "issues": report_data["issues"],
        },
    )
    try:
        convex_client.mutation("testSessions:addMessageToTestSession", {
            "testSessionId": test_session_id,
            "message": "Report created"
        })
    except Exception:
        pass
    
    return "Report generated and saved."
