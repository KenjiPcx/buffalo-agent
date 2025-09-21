#!/usr/bin/env python3
"""
Quick validation script: runs a speed-focused Reddit task with browser_use and prints the final result.
"""
import asyncio
import os
from browser_use import Agent
from configs import browser_llm, browser_profile

SPEED_OPTIMIZATION_PROMPT = (
    "Act fast. Prefer direct actions over explanations. Avoid unnecessary thinking output."
)

async def test_browser():
    """Run a speed-focused Reddit task and print the final result."""
    print("Testing browser_use in Docker environment (speed-focused task)...")
    
    try:
        task = (
            """
            1. Go to "buffalos.ai" and tell me what the website is about
            2. Return the website summary
            """
        )

        print("Creating agent (flash mode)...")
        agent = Agent(
            task=task,
            llm=browser_llm,
            flash_mode=True,
            browser_profile=browser_profile,
            extend_system_message=SPEED_OPTIMIZATION_PROMPT,
        )

        print("Agent created successfully!")
        print("Environment variables:")
        print(f"DISPLAY: {os.getenv('DISPLAY', 'Not set')}")
        print(f"PLAYWRIGHT_BROWSERS_PATH: {os.getenv('PLAYWRIGHT_BROWSERS_PATH', 'Not set')}")
        
        print("Running agent task...")
        history = await agent.run()

        # Extract and print final result similar to project helper behavior
        final_attr = getattr(history, "final_result", None)
        if callable(final_attr):
            result_text = str(final_attr())
        elif final_attr is not None:
            result_text = str(final_attr)
        else:
            result_text = str(history)

        print("===== FINAL RESULT =====")
        print(result_text)
        print("========================")
        
        print("Speed-focused test completed successfully!")
        
    except Exception as e:
        print(f"Browser test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = asyncio.run(test_browser())
    if success:
        print("✅ Browser test passed!")
        exit(0)
    else:
        print("❌ Browser test failed!")
        exit(1)
