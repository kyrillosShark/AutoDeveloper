import os
import logging
import sys
from dotenv import load_dotenv
from typing import Dict  # Import Dict here

# Load environment variables
load_dotenv()

# Configuration and constants
MAX_PROMPT_TOKENS = 8000  # Adjusted for GPT-4
PROMPT = '\x1b[32m$user@milo $\x1b[0m '  # Terminal prompt with green color

# OpenAI API key
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    raise ValueError(
        "OpenAI API key not found. Please set the OPENAI_API_KEY environment variable."
    )

FLICKR_API_KEY = os.getenv('FLICKR_API_KEY')
FLICKR_API_SECRET = os.getenv('FLICKR_API_SECRET') 

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s:%(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Global variables
file_paths = {}
code_source = None
original_prompt = None  # To store original prompt
testing_commands_list = []
retry_attempt = 1
MAX_ATTEMPTS = 0  # Maximum number of retry attempts
client_window_position = {}

# Remove get_all_scripts from here to avoid duplication
