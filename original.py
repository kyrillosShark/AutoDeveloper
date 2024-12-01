from flask import Flask, request, jsonify, render_template, send_file
from flask_socketio import SocketIO, emit
import subprocess
import sys
import os
import threading
import logging
import tempfile
import queue
import openai
import shutil
import re
import shlex
import atexit
from typing import Dict, List
import tiktoken
import pyautogui
from io import BytesIO
import base64
import json
import time
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import flickrapi


MAX_PROMPT_TOKENS = 8000  # Adjusted for GPT-4
load_dotenv()
# Initialize Flask app without Secret Key
app = Flask(__name__)

# Initialize Flask-SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False, ping_timeout=120, ping_interval=25)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s:%(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Global variable to store the client's window position
client_window_position = {}

@socketio.on('window_position', namespace='/terminal')
def handle_window_position(data):
    global client_window_position
    sid = request.sid  # Socket.IO session ID

    client_window_position[sid] = {
        'x': data.get('x', 0),
        'y': data.get('y', 0),
        'width': data.get('width', 800),
        'height': data.get('height', 600)
    }
    logging.debug(f"Received window position from client {sid}: {client_window_position[sid]}")

# Global variables (single session)
process = None
input_queue = queue.Queue()
file_paths = {}
code_source = None
original_prompt = None  # To store original prompt
testing_commands_list = []
retry_attempt = 1
# Constants
MAX_ATTEMPTS = 0  # Maximum number of retry attempts
PROMPT = '\x1b[32m$user@milo $\x1b[0m '  # Terminal prompt with green color

# OpenAI API key - Use environment variable
openai.api_key = os.getenv('OPENAI_API_KEY')

if not openai.api_key:
    raise ValueError("OpenAI API key not found. Please set the OPENAI_API_KEY environment variable.")


# Define Allowed Run Commands
ALLOWED_RUN_COMMANDS = [
    r'^python\s+\w+\.py(?:\s+.*)?$',
    r'^python3\s+\w+\.py(?:\s+.*)?$',
    r'^\./\w+$',
    # Add more patterns as needed
]

def estimate_tokens(text, model="gpt-4o"):
    """
    Estimates the number of tokens in the text for the specified model.
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")  # Fallback encoding
    return len(encoding.encode(text))

def get_language_from_extension(file_name):
    extension_language_map = {
        '.py': 'python',
        '.cpp': 'c++',
        '.c': 'c',
        '.html': 'html',
        '.css': 'css',
        '.js': 'javascript',
        '.java': 'java',
        '.cs': 'c#',
        # Add more mappings as needed
    }
    _, ext = os.path.splitext(file_name)
    return extension_language_map.get(ext.lower(), 'text')  # Default to 'text' if unknown

# Helper Functions
def is_valid_file_name(file_name):
    """
    Allow only alphanumeric characters, underscores, hyphens, and dots
    """
    regex = re.compile(r'^[a-zA-Z0-9_\-\.]+$')
    return regex.match(file_name) is not None

def create_file(file_name):
    """
    Helper function to create a file.
    Returns a tuple (status, message).
    """
    if not file_name:
        return (False, "File name not provided.")

    if not is_valid_file_name(file_name):
        return (False, "Invalid file name.")

    if file_name in file_paths:
        return (False, "File already exists.")

    try:
        session_dir = os.path.join(tempfile.gettempdir(), "compiler_session")
        os.makedirs(session_dir, exist_ok=True)
        file_path = os.path.join(session_dir, file_name)

        with open(file_path, 'a') as f:
            f.write('')  # Start with an empty file

        file_paths[file_name] = file_path
        logging.debug(f"File '{file_name}' created at '{file_path}'.")
        return (True, "File created successfully.")
    except Exception as e:
        logging.error(f"Error creating file '{file_name}': {e}")
        return (False, f"Failed to create file: {e}")
def fetch_flickr_image_data(query):
    """
    Fetches image data from Flickr based on the search query.

    Args:
        query (str): The search query.

    Returns:
        dict: A dictionary containing image URL and attribution information, or None if failed.
    """
    try:
        # Search for photos on Flickr
        photos = flickr.photos.search(
            text=query,
            per_page=1,
            sort='relevance',
            extras='url_c,owner_name'  # Get medium-sized URL and owner name
        )

        if photos['photos']['photo']:
            photo = photos['photos']['photo'][0]
            image_url = photo.get('url_c')  # Medium-sized image
            owner_name = photo.get('ownername', 'Unknown')
            if image_url:
                return {
                    'image_url': image_url,
                    'owner_name': owner_name
                }
            else:
                logging.error("No image URL available for the fetched photo.")
                return None
        else:
            logging.error(f"No photos found on Flickr for query '{query}'")
            return None
    except Exception as e:
        logging.error(f"Error fetching image from Flickr: {e}")
        return None

def parse_testing_commands(response_text):
    """
    Parses the OpenAI response assuming it's in JSON format.
    """
    # Strip code fences from the response
    response_text = strip_code_fences(response_text)

    try:
        data = json.loads(response_text)
        num_commands = data.get('number_of_commands')
        commands = data.get('commands')

        if not isinstance(num_commands, int) or not isinstance(commands, list):
            logging.error("Invalid JSON structure.")
            logging.error(f"Response received: '{response_text}'")
            return None

        if len(commands) != num_commands:
            logging.error(f"Number of commands ({num_commands}) does not match the commands list length ({len(commands)}).")
            logging.error(f"Commands received: {commands}")
            return None

        return commands
    except json.JSONDecodeError as e:
        logging.error(f"JSON parsing error: {e}")
        logging.error(f"Response received: '{response_text}'")
        return None

def strip_code_fences(text):
    """
    Removes markdown code fences from the text.
    """
    # Remove opening code fences (e.g., ```json or ```)
    text = re.sub(r'^```[\w]*\n', '', text)
    # Remove closing code fences
    text = text.replace('```', '')
    # Trim any leading/trailing whitespace
    return text.strip()

def save_generated_code(file_name, content):
    """
    Saves the generated code to the specified file.
    """
    # No need to create the file again; it's already ensured to exist
    file_path = file_paths.get(file_name)
    if not file_path:
        logging.error(f"File path for '{file_name}' not found.")
        return {"success": False, "message": "File path not found."}

    try:
        # Overwrite the existing file with new content
        with open(file_path, 'w') as f:
            f.write(content)
        logging.debug(f"Generated code saved to '{file_name}'.")
        return {"success": True}
    except Exception as e:
        logging.error(f"Failed to save generated code to '{file_name}': {e}")
        return {"success": False, "message": f"Failed to save file: {e}"}

def get_all_scripts() -> Dict[str, str]:
    """
    Retrieves all scripts.
    Returns a dictionary with filenames as keys and script contents as values.
    """
    scripts = {}
    for file_name, file_path in file_paths.items():
        try:
            with open(file_path, 'r') as f:
                scripts[file_name] = f.read()
        except Exception as e:
            logging.error(f"Error reading file '{file_name}': {e}")
            socketio.emit('message', {
                'type': 'error',
                'output': f"❌ Error reading file '{file_name}': {e}\r\n"
            }, namespace='/terminal')
    return scripts

def extract_code(text):
    """
    Extracts code from a text that may include explanations, comments, or code fences.

    Args:
        text (str): The raw text containing code and possibly other text.

    Returns:
        str: The extracted code.
    """
    # Remove code fences and any surrounding text
    code_pattern = re.compile(
        r'```(?:\w+)?\s*\n([\s\S]*?)```',
        re.MULTILINE
    )
    code_blocks = code_pattern.findall(text)
    if code_blocks:
        # If code blocks are found, join them
        code = '\n'.join(code_blocks).strip()
    else:
        # If no code blocks, assume entire text is code
        code = text.strip()

    # Remove any leading or trailing explanations or comments
    # For languages with single-line comments starting with '#', '//', or ';'
    code_lines = code.split('\n')
    cleaned_code_lines = []
    for line in code_lines:
        # Remove line if it starts with a common comment character
        if not line.strip().startswith(('#', '//', ';')):
            cleaned_code_lines.append(line)
    cleaned_code = '\n'.join(cleaned_code_lines).strip()
    return cleaned_code

def extract_command(command_response):
    """
    Extracts the command from OpenAI's response.
    Looks for content within code fences. If not found, returns the first non-empty line.
    """
    # Search for content within triple backticks
    code_fence_match = re.search(r'```(?:\w+)?\n([\s\S]*?)```', command_response)
    if code_fence_match:
        command = code_fence_match.group(1).strip()
        logging.debug(f"Extracted command from code fences: {command}")
        return command

    # If no code fences, fallback to the first non-empty line
    for line in command_response.strip().split('\n'):
        line = line.strip()
        if line and not line.startswith('#'):
            logging.debug(f"Extracted command from first valid line: {line}")
            return line
    return None

def is_valid_run_command(command):
    """
    Validates the run command against a whitelist of allowed commands.
    """
    for pattern in ALLOWED_RUN_COMMANDS:
        if re.match(pattern, command):
            return True
    return True

def start_execution_process(language):
    global process, input_queue

    if language == 'python':
        main_file = get_main_file()
        if not main_file:
            return {"status": "error", "error": "No main Python file found (e.g., main.py)."}
        exec_command = [sys.executable, '-u', main_file]
    elif language == 'c++' or language == 'c':
        source_files = [fp for fn, fp in file_paths.items() if fn.endswith('.cpp') or fn.endswith('.c')]
        if not source_files:
            return {"status": "error", "error": "No C/C++ source files found."}
        executable_path = os.path.join(tempfile.gettempdir(), "compiler_session", "program")
        compile_command = ['g++'] + source_files + ['-o', executable_path]
        try:
            compile_process = subprocess.run(compile_command, capture_output=True, text=True)
            if compile_process.returncode != 0:
                return {"status": "error", "error": f"Compilation failed:\r\n{compile_process.stderr}"}
            exec_command = [executable_path]
        except Exception as e:
            logging.error(f"Failed to compile C/C++ files: {e}")
            return {"status": "error", "error": f"Failed to compile C/C++ files: {e}"}
    elif language == 'html':
        # For HTML, no execution is needed
        return {"status": "display"}
    else:
        return {"status": "error", "error": f"Unsupported language: {language}."}

    try:
        process = subprocess.Popen(
            exec_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        input_queue = queue.Queue()
        input_thread = threading.Thread(target=handle_input, args=(process, input_queue))
        input_thread.start()
        logging.debug(f"Started subprocess with command: {' '.join(exec_command)}")
        return {"status": "success"}
    except Exception as e:
        logging.error(f"Failed to start subprocess: {e}")
        return {"status": "error", "error": f"Failed to start subprocess: {e}"}

def handle_input(process, input_queue):
    while True:
        try:
            user_input = input_queue.get(timeout=1)
            process.stdin.write(user_input + '\n')  # Use '\n' for proper input handling
            process.stdin.flush()
            logging.debug(f"Sent input to process: {user_input}")
        except queue.Empty:
            if process.poll() is not None:
                logging.debug("Process has terminated.")
                break
        except Exception as e:
            logging.error(f"Error in input handling: {e}")
            break

def get_main_file():
    """
    Determines the main file to execute based on naming conventions.
    """
    # Priority 1: main.html
    for file_name, path in file_paths.items():
        if file_name.lower() == 'main.html':
            return path

    # Priority 2: index.html
    for file_name, path in file_paths.items():
        if file_name.lower() == 'index.html':
            return path

    # Priority 3: Any other HTML file
    for file_name, path in file_paths.items():
        if file_name.lower().endswith('.html'):
            return path

    # Existing logic for other languages
    for file_name, path in file_paths.items():
        if file_name in ['main.py', 'main.cpp', 'main.c']:
            return path

    for file_name, path in file_paths.items():
        if file_name.endswith('.py') or file_name.endswith('.cpp') or file_name.endswith('.c'):
            return path

    return None

    return None

def get_language():
    """
    Retrieves the programming language based on the main file's extension.
    """
    main_file_path = get_main_file()
    if not main_file_path:
        return None

    _, ext = os.path.splitext(main_file_path)
    ext = ext.lstrip('.')
    extension_language_map = {
        'py': 'python',
        'cpp': 'c++',
        'c': 'c',
        'html': 'html',
        'js': 'javascript',
        'java': 'java',
        'cs': 'c#',
        # Add more extensions and their corresponding languages
    }
    return extension_language_map.get(ext, None)

def terminate_process():
    """
    Terminates the subprocess and cleans up.
    """
    global process
    if process:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
                logging.debug("Terminated subprocess.")
            except subprocess.TimeoutExpired:
                process.kill()
                logging.debug("Killed subprocess after timeout.")
        process = None
    # Clear input queue
    while not input_queue.empty():
        try:
            input_queue.get_nowait()
        except queue.Empty:
            break

def normalize_newlines(text):
    """
    Replaces carriage returns and CRLF with LF for consistency.
    """
    return text.replace('\r\n', '\n').replace('\r', '\n')

def cleanup():
    """
    Cleans up the subprocess and temporary directories on server shutdown.
    """
    terminate_process()
    session_dir = os.path.join(tempfile.gettempdir(), "compiler_session")
    if os.path.exists(session_dir):
        shutil.rmtree(session_dir, ignore_errors=True)

# Register cleanup function
atexit.register(cleanup)

# Routes

@app.route('/')
def index():
    # Create the default 'main.py' file
    status, message = create_file('main.py')
    if not status:
        logging.error(f"Failed to create default file: {message}")
        return "Failed to initialize session.", 500
    return render_template('index.html')  # Removed session_id

@app.route('/create_file', methods=['POST'])
def create_file_route():
    data = request.get_json()
    file_name = data.get('file_name')

    if not file_name:
        return jsonify({"error": "File name not provided."}), 400

    if not is_valid_file_name(file_name):
        return jsonify({"error": "Invalid file name."}), 400

    status, message = create_file(file_name)

    if status:
        return jsonify({"status": "success"}), 200
    elif message == "File already exists.":
        return jsonify({"status": "exists"}), 200
    else:
        return jsonify({"error": message}), 400

@app.route('/save_file/<file_name>', methods=['POST'])
def save_file_route(file_name):
    data = request.get_json()
    content = data.get('content')
    source = data.get('source', 'user')
    prompt = data.get('prompt')  # New: Retrieve the prompt if provided

    if not file_name:
        return jsonify({"error": "File name not provided."}), 400

    # Save the file
    status, message = create_file(file_name)
    if not status and message != "File already exists.":
        return jsonify({"error": message}), 400

    file_path = file_paths[file_name]

    try:
        with open(file_path, 'w') as f:
            f.write(content)

        logging.debug(f"File '{file_name}' saved with source '{source}'.")

        # If the source is 'milo' and a prompt is provided, store it
        if source == 'milo' and prompt:
            global original_prompt
            original_prompt = prompt
            logging.debug("Original prompt stored.")

        return jsonify({"status": "success"}), 200
    except Exception as e:
        logging.error(f"Failed to save file '{file_name}': {e}")
        return jsonify({"error": f"Failed to save file: {e}"}), 500

@app.route('/get_file/<file_name>', methods=['GET'])
def get_file_route(file_name):
    if file_name not in file_paths:
        return jsonify({"error": "File not found."}), 404

    file_path = file_paths[file_name]
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        return jsonify({"content": content, "file_name": file_name}), 200
    except Exception as e:
        logging.error(f"Failed to read file '{file_name}': {e}")
        return jsonify({"error": f"Failed to read file: {e}"}), 500

@app.route('/delete_file/<file_name>', methods=['POST'])
def delete_file_route(file_name):
    global code_source, original_prompt
    retry_attempt = 1
    if file_name not in file_paths:
        return jsonify({"error": "File not found."}), 404

    file_path = file_paths[file_name]
    try:
        os.remove(file_path)
        del file_paths[file_name]
        logging.debug(f"File '{file_name}' deleted.")

        session_dir = os.path.dirname(file_path)
        if not file_paths:
            shutil.rmtree(session_dir)
            logging.debug(f"Session directory '{session_dir}' removed.")
            code_source = None  # Reset code source
            original_prompt = None
            retry_attempt = 1

        return jsonify({"status": "success"}), 200
    except Exception as e:
        logging.error(f"Failed to delete file '{file_name}': {e}")
        return jsonify({"error": f"Failed to delete file: {e}"}), 500

def execute_command(commands=None):
    retry_attempt = 1
    """
    Executes the main script or a list of testing commands and handles output.
    """
    if commands is None:
        # Existing code for executing the main program
        language = get_language()
        if not language:
            socketio.emit('message', {
                'type': 'error',
                'output': '❌ Could not determine programming language.\r\n'
            }, namespace='/terminal')
            return

        # Terminate any existing process
        terminate_process()

        # Start the execution process
        result = start_execution_process(language)

        if result['status'] == 'error':
            socketio.emit('message', {
                'type': 'error',
                'output': f"❌ {result['error']}\n"
            }, namespace='/terminal')
            return
        elif result['status'] == 'display':
            # Handle displayable content (e.g., HTML)
            display_file()
            return

        socketio.emit('message', {
            'type': 'system',
            'output': f"⚡ Executing {language} code...\n"
        }, namespace='/terminal')

        def output_handler():
            global process

            if not process:
                logging.error("No process found during execution.")
                return 

            full_output = ""
            full_error = ""
            screenshot_path = None  # Initialize screenshot_path

            try:
                while True:
                    if process.poll() is not None:
                        # Process has terminated
                        remaining_output = process.stdout.read()
                        if remaining_output:
                            remaining_output = normalize_newlines(remaining_output)
                            full_output += remaining_output
                            socketio.emit('message', {'type': 'output', 'output': remaining_output}, namespace='/terminal')
                        remaining_error = process.stderr.read()
                        if remaining_error:
                            remaining_error = normalize_newlines(remaining_error)
                            socketio.emit('message', {'type': 'error', 'output': remaining_error}, namespace='/terminal')
                        break
                    output = process.stdout.readline()
                    if output:
                        output = normalize_newlines(output)
                        # Handle HTML output
                        if '<html' in output.lower():
                            socketio.emit('html_output', {'content': output}, namespace='/terminal')
                        else:
                            socketio.emit('message', {'type': 'output', 'output': output}, namespace='/terminal')
                        full_output += output
                    error = process.stderr.readline()
                    if error:
                        error = normalize_newlines(error)
                        socketio.emit('message', {'type': 'error', 'output': error}, namespace='/terminal')
                        full_error += error

                return_code = process.poll()
                socketio.emit('message', {
                    'type': 'system',
                    'output': f"[Process completed with return code: {return_code}]\r\n"
                }, namespace='/terminal')

                # Capture GUI screenshot if GUI or HTML code is detected
                if contains_gui_or_html_code():
                    screenshot_path = os.path.join(tempfile.gettempdir(), "compiler_session", "screenshot.png")
                    capture_screenshot(screenshot_path)
                    logging.debug(f"Captured screenshot at '{screenshot_path}'.")

                    # Send screenshot to frontend
                    if screenshot_path and os.path.exists(screenshot_path):
                        with open(screenshot_path, 'rb') as img_file:
                            image_data = img_file.read()
                            # Encode image in base64 to send via JSON
                            encoded_image = base64.b64encode(image_data).decode('utf-8')
                            socketio.emit('image_output', {'filename': 'screenshot.png', 'data': encoded_image}, namespace='/terminal')

                # Assess execution
                scripts = get_all_scripts()
                combined_output = f"{full_output}\n{full_error}"
                assessment_result = evaluate_execution(scripts, combined_output, screenshot_path)

                # Emit the assessment result and handle retry if necessary
                emit_assessment_result(assessment_result, combined_output, screenshot_path)

                # Emit prompt after execution
                socketio.emit('message', {'type': 'prompt', 'output': PROMPT}, namespace='/terminal')

            except Exception as e:
                logging.error(f"Error in output_handler: {e}")
                socketio.emit('message', {
                    'type': 'error',
                    'output': f"❌ Error during execution: {e}\r\n"
                }, namespace='/terminal')
                # Emit prompt even in case of error
                socketio.emit('message', {'type': 'prompt', 'output': PROMPT}, namespace='/terminal')

            finally:
                # Terminate the process
                terminate_process()

        output_thread = threading.Thread(target=output_handler)
        output_thread.start()

    else:
        # **Modification Starts Here**
        # Execute the list of testing commands
        combined_output = ""  # Initialize combined output

        for cmd in commands:
            # **Emit the command to the terminal before execution**
            # This makes the terminal display the command as if the user typed it
            socketio.emit('message', {'type': 'output', 'output': f"{PROMPT}{cmd}\r\n"}, namespace='/terminal')

            # Execute the command and capture output
            try:
                working_dir = os.path.join(tempfile.gettempdir(), "compiler_session")

                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=working_dir,
                    timeout=30
                )

                output = normalize_newlines(result.stdout.strip())
                error = normalize_newlines(result.stderr.strip())

                if output:
                    socketio.emit('message', {'type': 'output', 'output': f"{output}\r\n"}, namespace='/terminal')
                    combined_output += output + "\n"
                if error:
                    socketio.emit('message', {'type': 'error', 'output': f"{error}\r\n"}, namespace='/terminal')
                    combined_output += error + "\n"

                # Handle HTML output
                if '<html' in output.lower():
                    socketio.emit('html_output', {'content': output}, namespace='/terminal')

                # Emit return code if necessary
                if result.returncode != 0 or (not output and not error):
                    return_code_msg = f"[Process completed with return code: {result.returncode}]\r\n"
                    socketio.emit('message', {
                        'type': 'system',
                        'output': return_code_msg
                    }, namespace='/terminal')
                    combined_output += return_code_msg

                # **Handle GUI output after command execution**
                # Capture GUI screenshot if GUI or HTML code is detected
                if contains_gui_or_html_code():
                    screenshot_path = os.path.join(tempfile.gettempdir(), "compiler_session", "screenshot.png")
                    capture_screenshot(screenshot_path)
                    logging.debug(f"Captured screenshot at '{screenshot_path}'.")

                    # Send screenshot to frontend
                    if screenshot_path and os.path.exists(screenshot_path):
                        with open(screenshot_path, 'rb') as img_file:
                            image_data = img_file.read()
                            # Encode image in base64 to send via JSON
                            encoded_image = base64.b64encode(image_data).decode('utf-8')
                            socketio.emit('image_output', {'filename': 'screenshot.png', 'data': encoded_image}, namespace='/terminal')

            except subprocess.TimeoutExpired:
                timeout_msg = "❌ Command execution timed out.\r\n"
                socketio.emit('message', {
                    'type': 'error',
                    'output': timeout_msg
                }, namespace='/terminal')
                combined_output += timeout_msg
            except Exception as e:
                error_msg = f"❌ Failed to execute command '{cmd}': {e}\r\n"
                logging.error(error_msg)
                socketio.emit('message', {
                    'type': 'error',
                    'output': error_msg
                }, namespace='/terminal')
                combined_output += error_msg

        # Emit prompt after all commands are executed
        socketio.emit('message', {'type': 'prompt', 'output': PROMPT}, namespace='/terminal')

        # Assess execution based on combined output
        scripts = get_all_scripts()
        assessment_result = evaluate_execution(scripts, combined_output)

        # Emit the assessment result and handle retry if necessary
        emit_assessment_result(assessment_result, combined_output)
@socketio.on('display_html', namespace='/terminal')
def handle_display_html(data):
    file_name = data.get('file_name')
    if file_name:
        display_file(file_name)


@app.route('/generate_code', methods=['POST'])
def generate_code_route():
    """
    Flask route to handle code generation requests.
    """
    global code_source, original_prompt, testing_commands_list
    retry_attempt = 1

    data = request.get_json()
    prompt = data.get('prompt')
    language = data.get('language')

    if not prompt or not language:
        logging.error("Prompt or language not provided in /generate_code request.")
        return jsonify({"error": "Prompt or language not provided."}), 400

    try:
        original_prompt = prompt  # Store the original prompt

        # Step 1: Ask OpenAI for the number of scripts and their names
        file_extension = get_extension(language)
        file_list_prompt = (
            f"Based on the following project description, please list the number of files needed and their names "
            f"in the format: number_of_files,file1.{file_extension},file2.{file_extension}. "
            f"Do not include any explanations or code, just the file names.\n\n{prompt}"
        )

        # Estimate tokens and truncate if necessary
        prompt_token_count = estimate_tokens(file_list_prompt)
        if prompt_token_count > MAX_PROMPT_TOKENS:
            allowed_prompt_length = int(len(file_list_prompt) * (MAX_PROMPT_TOKENS / prompt_token_count))
            file_list_prompt = file_list_prompt[:allowed_prompt_length]
            logging.warning("File list prompt truncated due to token limit.")

        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": file_list_prompt}
            ],
            max_tokens=150,
            temperature=0.2
        )
        file_list_response = response.choices[0].message['content'].strip()
        logging.debug(f"File list response: {file_list_response}")

        # Step 2: Parse the response to get the number of files and file names
        parts = file_list_response.replace('[', '').replace(']', '').split(',')
        if len(parts) < 2:
            logging.error(f"Invalid file list response format: {file_list_response}")
            return jsonify({"error": "Invalid response format from OpenAI when requesting file list."}), 500

        try:
            num_files = int(parts[0].strip())
        except ValueError:
            logging.error(f"Invalid number of files provided: {parts[0].strip()}")
            return jsonify({"error": "Invalid number of files in OpenAI response."}), 500

        file_names = [fn.strip() for fn in parts[1:]]
        if len(file_names) != num_files:
            logging.error(f"Number of files ({num_files}) does not match the number of file names ({len(file_names)}).")
            return jsonify({"error": "Number of files does not match the number of file names in OpenAI response."}), 500

        # Step 3: Create files and notify frontend to create empty tabs
        for file_name in file_names:
            status, message = create_file(file_name)
            if not status and message != "File already exists.":
                logging.error(f"Failed to create file '{file_name}': {message}")
                return jsonify({"error": message}), 500

            # Emit an event to the frontend to create an empty tab
            socketio.emit('create_tab', {'file_name': file_name}, namespace='/terminal')
            logging.debug(f"'create_tab' event emitted for file '{file_name}'.")

        # Step 4: Generate code for each file with streaming
        all_generated_codes = {}
        for file_name in file_names:
            try:
                # Determine the language based on the file extension
                language_for_file = get_language_from_extension(file_name)
                if language_for_file == 'text':
                    logging.warning(f"Unsupported file type for '{file_name}'. Skipping code generation.")
                    socketio.emit('message', {
                        'type': 'error',
                        'output': f"❌ Unsupported file type for '{file_name}'. Skipping code generation.\r\n"
                    }, namespace='/terminal')
                    continue  # Skip unsupported file types

                # Generate code for the file with streaming
                code_prompt = (
                    f"Based on the following project description, write **only** the complete code for '{file_name}' "
                    f"in {language_for_file}. Do not include any explanations, comments, code fences, markdown, or any extra text. "
                    f"The response should be the pure code that can be directly used in '{file_name}'.\n\n"
                    f"If the project needs a GUI, the GUI window should be placed in the center of the screen and the window should correctly wrap around the contents, and be resizable and beautiful.\n"
                    f"### Project Description:\n{prompt}"
                )

                # Estimate token usage and truncate if necessary
                prompt_token_count = estimate_tokens(code_prompt)
                if prompt_token_count > MAX_PROMPT_TOKENS:
                    allowed_prompt_length = int(len(code_prompt) * (MAX_PROMPT_TOKENS / prompt_token_count))
                    code_prompt = code_prompt[:allowed_prompt_length]
                    logging.warning(f"Code prompt for '{file_name}' truncated due to token limit.")

                response = openai.ChatCompletion.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": f"You are a professional {language_for_file} developer who writes clean, well-structured code without any additional text or comments."},
                        {"role": "user", "content": code_prompt}
                    ],
                    max_tokens=2000,  # Adjust as needed
                    temperature=0.2,
                    stream=True  # Enable streaming
                )

                # Handle streaming response
                generated_code = ''
                for chunk in response:
                    # Check if 'choices' and 'delta' are present
                    if 'choices' in chunk and 'delta' in chunk['choices'][0]:
                        delta = chunk['choices'][0]['delta']
                        # Get 'content' if present
                        chunk_content = delta.get('content', '')
                        if chunk_content:
                            generated_code += chunk_content
                            # Add logging before emitting
                            logging.debug(f"Emitting code_chunk for file '{file_name}' with chunk length {len(chunk_content)}")
                            # Send the chunk to the frontend
                            socketio.emit('code_chunk', {
                                'chunk': chunk_content,
                                'file_name': file_name
                            }, namespace='/terminal')
                        else:
                            # No content in this chunk, do nothing
                            pass
                    else:
                        # No 'delta' in chunk, skip
                        pass

                logging.debug(f"Raw generated code for file '{file_name}':\n{generated_code}")

                # Extract only the code from the response
                generated_code = extract_code(generated_code)
                logging.debug(f"Processed generated code for file '{file_name}':\n{generated_code}")

                # Validate generated code length
                if not generated_code or len(generated_code) < 10:
                    logging.error(f"Received insufficient code for '{file_name}'.")
                    socketio.emit('message', {
                        'type': 'error',
                        'output': f"❌ Received insufficient code for '{file_name}'.\r\n"
                    }, namespace='/terminal')
                    continue  # Skip saving and emitting

                # Save the generated code to the file
                save_status = save_generated_code(file_name, generated_code)
                if not save_status['success']:
                    socketio.emit('message', {
                        'type': 'error',
                        'output': f"❌ Failed to save generated code for '{file_name}': {save_status['message']}\r\n"
                    }, namespace='/terminal')
                    continue  # Proceed to the next file

                all_generated_codes[file_name] = generated_code

                # Emit completion event for this file
                socketio.emit('code_generation_complete', {
                    'file_name': file_name
                }, namespace='/terminal')
                logging.debug(f"'code_generation_complete' event emitted for file '{file_name}'.")

            except openai.error.InvalidRequestError as e:
                logging.error(f"OpenAI API error while generating code for '{file_name}': {e}")
                if 'maximum context length' in str(e):
                    socketio.emit('message', {
                        'type': 'error',
                        'output': f"❌ The prompt for '{file_name}' is too long and exceeds the token limit.\r\n"
                    }, namespace='/terminal')
                else:
                    socketio.emit('message', {
                        'type': 'error',
                        'output': f"❌ OpenAI API error while generating code for '{file_name}': {e}\r\n"
                    }, namespace='/terminal')
                continue  # Proceed to the next file
            except Exception as e:
                logging.error(f"Error generating code for '{file_name}': {e}")
                socketio.emit('message', {
                    'type': 'error',
                    'output': f"❌ Error generating code for '{file_name}': {e}\r\n"
                }, namespace='/terminal')
                continue  # Proceed to the next file

        # Step 5: Ask OpenAI for testing commands
        if not all_generated_codes:
            logging.error("No code was generated for any files.")
            return jsonify({"error": "Failed to generate code for all files."}), 500

        testing_prompt = (
            f"Based on the scripts provided for the project description, how many terminal commands are needed to test this program? "
            f"Provide your answer in JSON format as follows:\n\n"
            f"{{\n  \"number_of_commands\": <number>,\n  \"commands\": [\"command1\", \"command2\", ...]\n}}\n\n"
            f"Each command should be a valid Linux terminal command that a user would type to run or test the program from the command line. "
            f"Do not include commands like 'open' that are specific to macOS. To display HTML files, just provide the filename (e.g., 'index.html'). "
            f"Do not include any additional text or explanations. Only provide the JSON object.\n\n"
            f"### Project Description:\n{prompt}\n\n"
            f"### Scripts:\n"
        )

        for file_name, content in all_generated_codes.items():
            # Limit each script to the first 100 lines to prevent exceeding token limits
            limited_content = '\n'.join(content.splitlines()[:100])
            testing_prompt += f"### {file_name}\n```\n{limited_content}\n```\n\n"

        # Estimate token usage and truncate if necessary
        testing_prompt_token_count = estimate_tokens(testing_prompt)
        if testing_prompt_token_count > MAX_PROMPT_TOKENS:
            allowed_script_tokens = MAX_PROMPT_TOKENS - estimate_tokens(
                f"Based on the scripts provided for the project description, how many commands are needed to test this program? Answer in this format: [number of commands], [example command], [example command]. Only provide the number and the commands in the specified format without additional explanations.\n\n### Project Description:\n{prompt}\n\n### Scripts:\n"
            )
            # Approximate character count based on tokens
            allowed_characters = allowed_script_tokens * 4  # Rough estimate
            testing_prompt = testing_prompt[:allowed_characters]
            logging.warning("Testing commands prompt truncated due to token limit.")

        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[
                    {"role": "user", "content": testing_prompt}
                ],
                max_tokens=500,  # Adjust as needed
                temperature=0.2
            )
            testing_commands_response = response.choices[0].message['content'].strip()
            logging.debug(f"Testing commands response: {testing_commands_response}")

            # Parse the testing commands response
            testing_commands = parse_testing_commands(testing_commands_response)
            if not testing_commands:
                logging.error("Failed to parse testing commands.")
                socketio.emit('message', {
                    'type': 'error',
                    'output': "❌ Failed to parse testing commands from OpenAI response.\r\n"
                }, namespace='/terminal')
                return jsonify({"error": "Failed to parse testing commands from OpenAI response."}), 500

            # Store the testing commands for later execution
            testing_commands_list = testing_commands

            # Emit an event to the frontend to display the testing commands
            socketio.emit('testing_commands', {'commands': testing_commands}, namespace='/terminal')

            code_source = 'milo'

            # Note: Do not start code execution here. Wait for the frontend to signal that typing is complete.

            return jsonify({"status": "success", "files": file_names}), 200

        except openai.error.InvalidRequestError as e:
            logging.error(f"OpenAI API error while generating testing commands: {e}")
            socketio.emit('message', {
                'type': 'error',
                'output': f"❌ OpenAI API error while generating testing commands: {e}\r\n"
            }, namespace='/terminal')
            return jsonify({"error": f"OpenAI API error: {e}"}), 500
        except openai.error.OpenAIError as e:
            logging.error(f"OpenAI API error while generating testing commands: {e}")
            socketio.emit('message', {
                'type': 'error',
                'output': f"❌ OpenAI API error while generating testing commands: {e}\r\n"
            }, namespace='/terminal')
            return jsonify({"error": f"OpenAI API error: {e}"}), 500
    except Exception as e:
        logging.error(f"Error in generate_code_route: {e}")
        socketio.emit('message', {
            'type': 'error',
            'output': f"❌ An error occurred: {e}\r\n"
        }, namespace='/terminal')
        return jsonify({"error": f"An error occurred: {e}"}), 500

def evaluate_execution(scripts: Dict[str, str], terminal_output: str, screenshot_path: str = None) -> int:
    """
    Evaluates whether the terminal output signifies that the program is working correctly.

    Args:
        scripts (Dict[str, str]): A dictionary where keys are filenames and values are their respective contents.
        terminal_output (str): The output from the terminal after executing the program.
        screenshot_path (str, optional): Path to the screenshot image if GUI output was captured.

    Returns:
        int: Returns 1 if the program is working correctly, 0 otherwise.
    """
    # Construct the scripts information
    scripts_info = ""
    for file_name, content in scripts.items():
        scripts_info += f"### {file_name}\n```\n{content}\n```\n\n"

    # Include a note about GUI output if a screenshot was captured
    gui_output_note = ""
    if screenshot_path and os.path.exists(screenshot_path):
        gui_output_note = "Note: The program produced GUI output which was captured as a screenshot."

    # Construct the assessment prompt
    assessment_prompt = (
        f"Based on the following scripts and their content, along with the terminal output, determine if the program ran successfully.\n\n"
        f"### Project Description:\n{original_prompt}\n\n"
        f"### Scripts:\n{scripts_info}"
        f"### Terminal Output:\n```\n{terminal_output}\n```\n\n"
        f"{gui_output_note}\n\n"
        f"Did the program execute successfully and produce the expected output based on the project description? Respond with `1` for yes and `0` for no."
    )

    try:
        # Call OpenAI's ChatCompletion API
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an assistant that evaluates the success of program executions based on code, output, and project description."},
                {"role": "user", "content": assessment_prompt}
            ],
            max_tokens=100,  # Minimal tokens as we expect a short response
            temperature=0  # Low temperature for deterministic output
        )

        # Extract the response content
        assessment = response.choices[0].message['content'].strip()

        # Parse the response to get 1 or 0
        if assessment.startswith('1'):
            return 1
        else:
            return 0

    except openai.error.OpenAIError as e:
        logging.error(f"OpenAI API error during evaluation: {e}")
        return 0  # Default to failure on API error

def fix_scripts_and_retry(scripts, terminal_output, attempt=1, screenshot_path=None):
    """
    Attempts to fix the scripts based on the terminal output and retries execution.

    Args:
        scripts (Dict[str, str]): The current scripts.
        terminal_output (str): The terminal output indicating failure.
        attempt (int): Current attempt number.
        screenshot_path (str, optional): Path to the screenshot image if GUI output was captured.

    Returns:
        None
    """
    retry_attempt = attempt

    if attempt > MAX_ATTEMPTS:
        logging.error("Max retry attempts reached.")
        socketio.emit('message', {
            'type': 'error',
            'output': "❌ Maximum retry attempts reached. Please review your code manually.\r\n"
        }, namespace='/terminal')
        return

    # Retrieve the original prompt
    if not original_prompt:
        logging.error("No original prompt found.")
        socketio.emit('message', {
            'type': 'error',
            'output': "❌ Original prompt not found. Cannot attempt to fix scripts.\r\n"
        }, namespace='/terminal')
        return

    # Include GUI output note if applicable
    gui_output_note = ""
    if screenshot_path and os.path.exists(screenshot_path):
        gui_output_note = "Note: The program produced GUI output which was captured as a screenshot."

    # Construct the prompt to fix the scripts
    fix_prompt = (
        f"Based on the following project description, current scripts, and terminal output, please identify the lines that cause the error and provide the corrected code for those lines.\n\n"
        f"For each affected file, list the line numbers that need to be changed and the new code for those lines. Use the following format:\n\n"
        f"### filename\nLine line_number: new code\n\n"
        f"Do not include any additional explanations.\n\n"
        f"### Project Description:\n{original_prompt}\n\n"
        f"### Current Scripts:\n"
    )
    for file_name, content in scripts.items():
        fix_prompt += f"### {file_name}\n```\n{content}\n```\n\n"

    fix_prompt += f"### Terminal Output:\n```\n{terminal_output}\n```\n\n"
    fix_prompt += f"{gui_output_note}\n\n"

    try:
        # Call OpenAI's API to fix the scripts
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an assistant that fixes programming code based on error outputs."},
                {"role": "user", "content": fix_prompt}
            ],
            max_tokens=2000,
            temperature=0.2
        )

        fixed_scripts_raw = response.choices[0].message['content'].strip()
        logging.debug(f"Raw fixed scripts response:\n{fixed_scripts_raw}")

        # Parse the fixed scripts
        scripts_changes = parse_fixed_scripts(fixed_scripts_raw)
        if not scripts_changes:
            logging.error("Failed to parse fixed scripts.")
            socketio.emit('message', {
                'type': 'error',
                'output': "❌ Failed to parse fixed scripts from the response.\r\n"
            }, namespace='/terminal')
            return

        # Apply the changes and emit updates to the frontend
        for file_name, changes in scripts_changes.items():
            if file_name not in file_paths:
                logging.error(f"File '{file_name}' not found.")
                socketio.emit('message', {
                    'type': 'error',
                    'output': f"❌ File '{file_name}' not found.\r\n"
                }, namespace='/terminal')
                continue
            file_path = file_paths[file_name]
            try:
                # Read the current content
                with open(file_path, 'r') as f:
                    lines = f.readlines()
                # Apply the changes
                for change in changes:
                    line_number = change['line_number']
                    new_code = change['new_code']
                    # Line numbers are 1-based, so adjust index
                    index = line_number - 1
                    if 0 <= index < len(lines):
                        old_line = lines[index]
                        lines[index] = new_code + '\n'
                        # Emit an event to the frontend to update the line
                        socketio.emit('update_line', {
                            'file_name': file_name,
                            'line_number': line_number,
                            'new_code': new_code
                        }, namespace='/terminal')
                    else:
                        logging.error(f"Invalid line number {line_number} in file '{file_name}'.")
                # Write back the updated content
                with open(file_path, 'w') as f:
                    f.writelines(lines)
                logging.debug(f"Updated file '{file_name}' with changes.")

            except Exception as e:
                logging.error(f"Failed to update file '{file_name}': {e}")
                socketio.emit('message', {
                    'type': 'error',
                    'output': f"❌ Failed to update file '{file_name}': {e}\r\n"
                }, namespace='/terminal')
                continue

        # Update the retry attempts
        retry_attempt = attempt

        # Call execute_command to retry execution
        socketio.start_background_task(execute_command, testing_commands_list)

    except openai.error.OpenAIError as e:
        logging.error(f"OpenAI API error during script fixing: {e}")
        socketio.emit('message', {
            'type': 'error',
            'output': f"❌ OpenAI API error during script fixing: {e}\r\n"
        }, namespace='/terminal')

def parse_fixed_scripts(fixed_scripts_raw: str) -> Dict[str, List[Dict[str, str]]]:
    """
    Parses the raw fixed scripts returned by OpenAI and extracts the changes.

    Args:
        fixed_scripts_raw (str): Raw response from OpenAI containing line changes.

    Returns:
        Dict[str, List[Dict[str, str]]]: A dictionary where keys are filenames, and values are lists of dictionaries with 'line_number' and 'new_code'.
    """
    scripts_changes = {}
    # Split by file sections
    file_sections = re.split(r'###\s*(\S+)\s*', fixed_scripts_raw)
    # file_sections[0] is the text before the first ###, so we can ignore it
    # Then, file_sections[1] is the first file name, file_sections[2] is the content, etc.
    for i in range(1, len(file_sections), 2):
        file_name = file_sections[i].strip()
        content = file_sections[i+1].strip()
        # Now, find all line changes in content
        line_changes = re.findall(r'Line\s+(\d+):\s*(.*)', content)
        changes = []
        for line_num_str, new_code in line_changes:
            line_number = int(line_num_str)
            changes.append({'line_number': line_number, 'new_code': new_code})
        scripts_changes[file_name] = changes
    return scripts_changes

def emit_assessment_result(assessment_result, terminal_output, screenshot_path=None):
    """
    Emits the assessment result and triggers retry if the execution failed.

    Args:
        assessment_result (int): 1 for success, 0 for failure.
        terminal_output (str): The terminal output from execution.
        screenshot_path (str, optional): Path to the screenshot image if GUI output was captured.

    Returns:
        None
    """
    retry_attempt = 1
    if assessment_result == 1:
        socketio.emit('message', {
            'type': 'system',
            'output': "✅ Program executed successfully.\r\n"
        }, namespace='/terminal')
    else:
        socketio.emit('message', {
            'type': 'system',
            'output': f"❌ Program execution failed. Attempting to fix... (Attempt {retry_attempt + 1}/{MAX_ATTEMPTS})\r\n"
        }, namespace='/terminal')
        scripts = get_all_scripts()
        fix_scripts_and_retry(scripts, terminal_output, retry_attempt + 1, screenshot_path)

def display_file(file_name=None):
    """
    Reads the specified file and emits its content to the frontend for display.
    If no file is specified, it determines the main file.
    """
    if file_name:
        main_file_path = file_paths.get(file_name)
        if not main_file_path:
            socketio.emit('message', {
                'type': 'error',
                'output': f"❌ File '{file_name}' not found.\r\n"
            }, namespace='/terminal')
            return
    else:
        main_file_path = get_main_file()
        if not main_file_path:
            socketio.emit('message', {
                'type': 'error',
                'output': '❌ Main file not found.\r\n'
            }, namespace='/terminal')
            return

    try:
        with open(main_file_path, 'r') as f:
            content = f.read()

        # Determine content type based on file extension
        _, ext = os.path.splitext(main_file_path)
        if ext.lower() == '.html':
            # Process the HTML content to replace image sources
            processed_content = process_html_content(content)
            socketio.emit('html_output', {'content': processed_content}, namespace='/terminal')
        else:
            socketio.emit('message', {'type': 'output', 'output': content}, namespace='/terminal')
        logging.debug(f"Emitted content of '{main_file_path}' to frontend.")
    except Exception as e:
        logging.error(f"Failed to read file '{main_file_path}': {e}")
        socketio.emit('message', {
            'type': 'error',
            'output': f"❌ Failed to read file '{main_file_path}': {e}\r\n"
        }, namespace='/terminal')
def process_html_content(html_content):
    """
    Parses the HTML content, finds all <img> tags, fetches images from Flickr,
    replaces the src attributes, and adds attribution.

    Args:
        html_content (str): The raw HTML content.

    Returns:
        str: The modified HTML content with updated image sources and attributions.
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    # Find all <img> tags
    img_tags = soup.find_all('img')

    for img in img_tags:
        # Get the alt text or use a default query
        query = img.get('alt', 'fitness')  # Changed default to 'fitness' for relevance

        # Fetch image data from Flickr
        image_data = fetch_flickr_image_data(query)

        if image_data:
            # Replace the src attribute
            img['src'] = image_data['image_url']
            # Add attribution
            attribution = soup.new_tag('p')
            attribution.string = f"Image by {image_data['owner_name']} on Flickr"
            img.insert_after(attribution)
        else:
            logging.error(f"Failed to fetch image for query '{query}'")
            # Optionally, set a placeholder image
             # Placeholder image

    # Return the modified HTML content
    return str(soup)


def get_extension(language):
    language_extensions = {
        'python': 'py',
        'c++': 'cpp',
        'c': 'c',
        'html': 'html',
        'javascript': 'js',
        'java': 'java',
        'c#': 'cs',
        # Add more languages and their extensions as needed
    }
    return language_extensions.get(language.lower(), 'txt')

def contains_gui_or_html_code():
    """
    Checks if any of the scripts contain GUI or HTML code.
    """
    scripts = get_all_scripts()
    for content in scripts.values():
        if ('import tkinter' in content or 'from tkinter' in content or
            '<html' in content.lower() or 'import pygame' in content or
            'from PyQt5' in content):
            return True
    return False

def capture_screenshot(screenshot_path):
    """
    Captures a screenshot and saves it to the given path.
    """
    try:
        # Capture the entire screen
        screenshot = pyautogui.screenshot()
        screenshot.save(screenshot_path)
    except Exception as e:
        logging.error(f"Failed to capture screenshot: {e}")

@app.route('/send_input', methods=['POST'])
def send_input_route():
    global input_queue

    data = request.get_json()
    user_input = data.get('input')

    if user_input is None:
        return jsonify({"error": "No input provided."}), 400

    input_queue.put(user_input)
    logging.debug(f"Received input: {user_input}")
    return jsonify({"status": "success"}), 200

# Socket.IO Event Handlers

@socketio.on('connect', namespace='/terminal')
def handle_connect():
    logging.debug("A client connected to /terminal namespace.")

    # Emit system message
    emit('message', {
        'type': 'system',
        'output': 'Connected to terminal.\r\n'
    })

    # Emit prompt
    emit('message', {'type': 'prompt', 'output': PROMPT})

@socketio.on('disconnect', namespace='/terminal')
def handle_disconnect():
    logging.debug("A client disconnected from /terminal namespace.")
    terminate_process()

@socketio.on('command', namespace='/terminal')
def handle_command_socketio(data):
    """
    Handles command events from the client via Socket.IO.
    Differentiates between automation-initiated commands and user-initiated commands.
    Only performs execution evaluation and script fixing for automation commands.
    """
    command = data.get('command')
    source = data.get('source', 'user')  # Default to 'user' if 'source' not provided

    if not command:
        emit('message', {'type': 'error', 'output': '❌ Command not provided.\r\n'})
        emit('message', {'type': 'prompt', 'output': PROMPT})
        return

    # Clean the command from markdown code fences if present
    command = re.sub(r'^```\w*\n?|\n?```$', '', command).strip()
    logging.debug(f"Received 'command' event with command: '{command}' from source: '{source}'")

    if process:
        if command == 'SIGINT':
            # Handle Ctrl+C
            try:
                process.send_signal(subprocess.signal.SIGINT)
                logging.debug("Sent SIGINT to process.")
                emit('message', {'type': 'output', 'output': '^C\r\n'})
            except Exception as e:
                logging.error(f"Failed to send SIGINT to process: {e}")
                emit('message', {'type': 'error', 'output': f"❌ Failed to send SIGINT: {e}\r\n"})
            # Do not emit prompt here; the process might still be running
            return
        else:
            # Send the command as input to the running process
            input_queue.put(command)
            logging.debug(f"Sent input to process: '{command}'")
            # Do not emit prompt; waiting for process input
            return

    # Else, treat it as a shell command
    allowed_commands = [
        'ls', 'pwd', 'echo', 'cat', 'mkdir', 'rm', 'cp', 'mv',
        'grep', 'find', 'head', 'tail', 'chmod', 'chown', 'touch',
        'python', 'python3', './program', 'gcc', 'g++', 'make', 'java', 'javac', 'node'
    ]

    # Define commands that are used to run user code
    code_execution_commands = [
        r'^python\s+\w+\.py(?:\s+.*)?$',
        r'^python3\s+\w+\.py(?:\s+.*)?$',
        r'^\./\w+$',
        # Add more patterns as needed
    ]

    try:
        cmd_parts = shlex.split(command)
        if not cmd_parts:
            emit('message', {'type': 'error', 'output': '❌ Empty command.\r\n'})
            emit('message', {'type': 'prompt', 'output': PROMPT})
            return
        base_cmd = cmd_parts[0]
        if base_cmd not in allowed_commands:
            # Check if base_cmd is an HTML file in file_paths
            if base_cmd in file_paths and base_cmd.endswith('.html'):
                # Display the HTML file
                display_html_file(base_cmd)
                # Emit prompt after execution
                emit('message', {'type': 'prompt', 'output': PROMPT})
                return
            else:
                emit('message', {'type': 'error', 'output': f"❌ Command '{base_cmd}' is not allowed.\r\n"})
                emit('message', {'type': 'prompt', 'output': PROMPT})
                return
    except Exception as e:
        emit('message', {'type': 'error', 'output': f"❌ Invalid command syntax: {e}\r\n"})
        emit('message', {'type': 'prompt', 'output': PROMPT})
        return

    try:
        working_dir = os.path.join(tempfile.gettempdir(), "compiler_session")

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=30
        )

        output = normalize_newlines(result.stdout.strip())
        error = normalize_newlines(result.stderr.strip())

        if output:
            emit('message', {'type': 'output', 'output': f"{output}\r\n"})
        if error:
            emit('message', {'type': 'error', 'output': f"{error}\r\n"})

        # Handle HTML output
        if '<html' in output.lower():
            emit('html_output', {'content': output})

        # Only emit return code if it's non-zero or if there was no output/error
        if result.returncode != 0 or (not output and not error):
            emit('message', {
                'type': 'system',
                'output': f"[Process completed with return code: {result.returncode}]\r\n"
            })

        # Check if the command is intended to execute user code
        is_code_execution = any(re.match(pattern, command) for pattern in code_execution_commands)

        if is_code_execution and source == 'automation':
            # Assess execution only for automation-initiated commands
            scripts = get_all_scripts()
            combined_output = f"{output}\n{error}"

            # Capture GUI screenshot if GUI or HTML code is detected
            screenshot_path = None
            if contains_gui_or_html_code():
                screenshot_path = os.path.join(tempfile.gettempdir(), "compiler_session", "screenshot.png")
                capture_screenshot(screenshot_path)
                logging.debug(f"Captured screenshot at '{screenshot_path}'.")

                # Send screenshot to frontend
                if screenshot_path and os.path.exists(screenshot_path):
                    with open(screenshot_path, 'rb') as img_file:
                        image_data = img_file.read()
                        # Encode image in base64 to send via JSON
                        encoded_image = base64.b64encode(image_data).decode('utf-8')
                        emit('image_output', {'filename': 'screenshot.png', 'data': encoded_image})

            # Evaluate execution
            assessment_result = evaluate_execution(scripts, combined_output, screenshot_path)

            # Emit the assessment result and handle retry if necessary
            emit_assessment_result(assessment_result, combined_output, screenshot_path)
        else:
            logging.debug("Execution assessment skipped (either not a code execution command or not from automation).")

        # Emit prompt after command execution
        emit('message', {'type': 'prompt', 'output': PROMPT})

    except subprocess.TimeoutExpired:
        emit('message', {
            'type': 'error',
            'output': "❌ Command execution timed out.\r\n"
        })
        # Emit prompt after timeout
        emit('message', {'type': 'prompt', 'output': PROMPT})
    except Exception as e:
        logging.error(f"Error executing command: {e}")
        emit('message', {
            'type': 'error',
            'output': f"❌ Failed to execute command: {e}\r\n"
        })
        # Emit prompt after error
        emit('message', {'type': 'prompt', 'output': PROMPT})

def execute_single_command(command):
    """
    Executes a single command and emits the output to the client.

    Args:
        command (str): The command to execute.
    """
    try:
        working_dir = os.path.join(tempfile.gettempdir(), "compiler_session")

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=30
        )

        output = normalize_newlines(result.stdout.strip())
        error = normalize_newlines(result.stderr.strip())

        if output:
            socketio.emit('message', {'type': 'output', 'output': f"{output}\r\n"}, namespace='/terminal')
        if error:
            socketio.emit('message', {'type': 'error', 'output': f"{error}\r\n"}, namespace='/terminal')

        # Handle HTML output
        if '<html' in output.lower():
            socketio.emit('html_output', {'content': output}, namespace='/terminal')

        # Emit return code if necessary
        if result.returncode != 0 or (not output and not error):
            socketio.emit('message', {
                'type': 'system',
                'output': f"[Process completed with return code: {result.returncode}]\r\n"
            }, namespace='/terminal')

    except subprocess.TimeoutExpired:
        socketio.emit('message', {
            'type': 'error',
            'output': "❌ Command execution timed out.\r\n"
        }, namespace='/terminal')
    except Exception as e:
        logging.error(f"Error executing command '{command}': {e}")
        socketio.emit('message', {
            'type': 'error',
            'output': f"❌ Failed to execute command '{command}': {e}\r\n"
        }, namespace='/terminal')

def display_html_file(file_name):
    """
    Reads an HTML file and emits its content to the frontend for display.

    Args:
        file_name (str): The name of the HTML file to display.
    """
    if file_name not in file_paths:
        socketio.emit('message', {
            'type': 'error',
            'output': f"❌ File '{file_name}' not found.\r\n"
        }, namespace='/terminal')
        return

    file_path = file_paths[file_name]
    try:
        with open(file_path, 'r') as f:
            html_content = f.read()
        socketio.emit('html_output', {'content': html_content}, namespace='/terminal')
        logging.debug(f"Emitted HTML content for '{file_name}'.")
    except Exception as e:
        logging.error(f"Failed to read HTML file '{file_name}': {e}")
        socketio.emit('message', {
            'type': 'error',
            'output': f"❌ Failed to read HTML file '{file_name}': {e}\r\n"
        }, namespace='/terminal')

def display_html_file(file_name):
    """
    Reads an HTML file and emits its content to the frontend for display.

    Args:
        file_name (str): The name of the HTML file to display.
    """
    if file_name not in file_paths:
        socketio.emit('message', {
            'type': 'error',
            'output': f"❌ File '{file_name}' not found.\r\n"
        }, namespace='/terminal')
        return

    file_path = file_paths[file_name]
    try:
        with open(file_path, 'r') as f:
            html_content = f.read()
        socketio.emit('html_output', {'content': html_content}, namespace='/terminal')
        logging.debug(f"Emitted HTML content for '{file_name}'.")
    except Exception as e:
        logging.error(f"Failed to read HTML file '{file_name}': {e}")
        socketio.emit('message', {
            'type': 'error',
            'output': f"❌ Failed to read HTML file '{file_name}': {e}\r\n"
        }, namespace='/terminal')


@socketio.on('execute', namespace='/terminal')
def execute_command_event():
    """
    Executes the main script.
    """
    socketio.start_background_task(execute_command)

@app.route('/capture_screenshot', methods=['GET'])
def capture_screenshot_route():
    try:
        # Capture the entire screen
        screenshot = pyautogui.screenshot()
        # Save the screenshot to a BytesIO object
        img_io = BytesIO()
        screenshot.save(img_io, 'PNG')
        img_io.seek(0)
        return send_file(img_io, mimetype='image/png')
    except Exception as e:
        logging.error(f"Failed to capture screenshot: {e}")
        return jsonify({"error": f"Failed to capture screenshot: {e}"}), 500

UPLOAD_FOLDER = tempfile.gettempdir()
ALLOWED_EXTENSIONS = {'py', 'cpp', 'c', 'js', 'html'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/package_executable', methods=['POST'])
def package_executable():
    data = request.get_json()
    file_name = data.get('file_name')
    code = data.get('code')
    language = data.get('language')

    if not file_name or not code or not language:
        return jsonify({'error': 'Missing required parameters.'}), 400

    if not allowed_file(file_name):
        return jsonify({'error': 'Unsupported file extension.'}), 400

    # Create a temporary directory to work in
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Define file paths
            code_file_path = os.path.join(temp_dir, file_name)
            executable_path = ''
            
            # Write the code to a file
            with open(code_file_path, 'w') as code_file:
                code_file.write(code)
            
            # Handle different languages
            if language == 'python':
                # Use PyInstaller to create executable
                subprocess.check_call([
                    'pyinstaller',
                    '--onefile',
                    '--distpath', temp_dir,
                    code_file_path
                ])
                # Find the executable
                executable_name = os.path.splitext(file_name)[0]
                executable_path = os.path.join(temp_dir, executable_name)
                if os.name == 'nt':
                    executable_path += '.exe'
                if not os.path.exists(executable_path):
                    return jsonify({'error': 'Executable not found after packaging.'}), 500

            elif language == 'cpp' or language == 'c':
                # Compile C++ or C code using g++
                if language == 'cpp':
                    output_executable = os.path.join(temp_dir, 'program')
                elif language == 'c':
                    output_executable = os.path.join(temp_dir, 'program_c')
                # On Windows, append .exe
                if os.name == 'nt':
                    output_executable += '.exe'
                subprocess.check_call([
                    'g++',
                    code_file_path,
                    '-o',
                    output_executable
                ])
                executable_path = output_executable
                if not os.path.exists(executable_path):
                    return jsonify({'error': 'Executable not found after compilation.'}), 500

            else:
                return jsonify({'error': 'Language not supported for packaging.'}), 400

            # Zip the executable
            zip_path = os.path.join(temp_dir, 'executable.zip')
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                zipf.write(executable_path, os.path.basename(executable_path))

            # Send the zip file as a downloadable attachment
            return send_file(
                zip_path,
                mimetype='application/zip',
                as_attachment=True,
                attachment_filename='executable.zip'
            )
        
        except subprocess.CalledProcessError as e:
            return jsonify({'error': f'An error occurred during packaging: {str(e)}'}), 500
        except Exception as e:
            return jsonify({'error': f'Unexpected error: {str(e)}'}), 500

def emit_screenshot_update():
    try:
        # Emit an event indicating that a new screenshot is available
        socketio.emit('new_screenshot', {'message': 'A new screenshot is available.'}, namespace='/terminal')
        logging.debug("Emitted 'new_screenshot' event to frontend.")
    except Exception as e:
        logging.error(f"Failed to emit screenshot update: {e}")
    

# Run the Flask app with SocketIO
if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5001)