# Use Google Gemini model
import os
from browser_use import BrowserProfile, ChatGoogle
from convex import ConvexClient
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from firecrawl import Firecrawl

load_dotenv()

model = init_chat_model(
    model=os.getenv("MODEL_NAME", "gpt-4.1-mini"),
    model_provider=os.getenv("MODEL_PROVIDER", "openai"),
    api_key=os.getenv("MODEL_API_KEY"),
    temperature=os.getenv("MODEL_TEMPERATURE", "0.3"),
    max_tokens=os.getenv("MODEL_MAX_TOKENS", "16000"),
    base_url=os.getenv("MODEL_BASE_URL", None)
)

# Initialize Convex client
CONVEX_URL = os.getenv("CONVEX_URL", "https://your-project.convex.cloud")
convex_client = ConvexClient(CONVEX_URL)

browser_llm = ChatGoogle(
    model=os.getenv("BROWSER_USE_MODEL_NAME", "gemini-2.5-flash"),
    temperature=0.9,
    api_key=os.getenv("BROWSER_USE_MODEL_API_KEY")
)

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
    wait_for_network_idle_page_load_time=1.0,  # Reduced for faster execution
    maximum_wait_page_load_time=5.0,  # Reduced timeout
    wait_between_actions=0.3  # Faster actions
)

def get_screen_dimensions():
    """Get screen dimensions with fallback for headless environments"""
    try:
        import screeninfo
        screen = screeninfo.get_monitors()[0]
        return screen.width, screen.height
    except Exception:
        return 1920, 1080

firecrawl_client = Firecrawl(api_key=os.getenv("FIRECRAWL_API_KEY"))