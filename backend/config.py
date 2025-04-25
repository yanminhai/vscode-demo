# Useful for debugging purposes when you don't want to waste GPT4-Vision credits
# Setting to True will stream a mock response instead of calling the OpenAI API
# TODO: Should only be set to true when value is 'True', not any abitrary truthy value
import os

NUM_VARIANTS = 3

# LLM-related
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", None)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", None)
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", None)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", None)
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", None)
# 新增模型:deepseek
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY",None)
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", None)
# 新增模型:通义千问
QWEN_API_KEY = os.environ.get("QWEN_API_KEY",None)
QWEN_BASE_URL = os.environ.get("QWEN_BASE_URL", None)
# 新增模型: InternVL
INTERN_VL_API_KEY = os.environ.get("INTERN_VL_API_KEY", None)
INTERN_VL_BASE_URL = os.environ.get("INTERN_VL_BASE_URL", None)

# Image generation (optional)
REPLICATE_API_KEY = os.environ.get("REPLICATE_API_KEY", None)

# Debugging-related

SHOULD_MOCK_AI_RESPONSE = bool(os.environ.get("MOCK", False))
IS_DEBUG_ENABLED = bool(os.environ.get("IS_DEBUG_ENABLED", False))
DEBUG_DIR = os.environ.get("DEBUG_DIR", "")

# Set to True when running in production (on the hosted version)
# Used as a feature flag to enable or disable certain features
IS_PROD = os.environ.get("IS_PROD", False)
