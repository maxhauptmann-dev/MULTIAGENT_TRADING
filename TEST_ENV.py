#✅

from dotenv import load_dotenv
import os

load_dotenv()

print("OpenAI Key:", os.getenv("OPENAI_API_KEY"))

import os
from dotenv import load_dotenv

load_dotenv()
print("OPENAI_API_KEY:", os.getenv("OPENAI_API_KEY"))
print("IBKR_BASE_URL:", os.getenv("IBKR_BASE_URL"))
print("FINNHUB_API_KEY:", os.getenv("FINNHUB_API_KEY"))
print("SERPAPI_API_KEY:", os.getenv("SERPAPI_API_KEY"))