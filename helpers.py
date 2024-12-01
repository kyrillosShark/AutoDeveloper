import re
import os
import logging
from bs4 import BeautifulSoup
import base64
import tempfile
import pyautogui
from typing import Dict, List
import json
import subprocess
from config import file_paths, FLICKR_API_KEY, FLICKR_API_SECRET
from app import socketio
import flickrapi

# Initialize the Flickr API client
flickr = flickrapi.FlickrAPI(FLICKR_API_KEY, FLICKR_API_SECRET, format='parsed-json')


def is_valid_file_name(file_name):
    """
    Allow only alphanumeric characters, underscores, hyphens, and dots.
    """
    regex = re.compile(r'^[a-zA-Z0-9_\-\.]+$')
    return regex.match(file_name) is not None
def get_language_from_extension(file_name):
    """
    Determines the programming language based on the file extension.
    """
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

def normalize_newlines(text):
    """
    Replaces carriage returns and CRLF with LF for consistency.
    """
    return text.replace('\r\n', '\n').replace('\r', '\n')

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

def extract_code(text):
    """
    Extracts code from a text that may include explanations, comments, or code fences.
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
    ALLOWED_RUN_COMMANDS = [
        r'^python\s+\w+\.py(?:\s+.*)?$',
        r'^python3\s+\w+\.py(?:\s+.*)?$',
        r'^\./\w+$',
        # Add more patterns as needed
    ]
    for pattern in ALLOWED_RUN_COMMANDS:
        if re.match(pattern, command):
            return True
    return False



def get_extension(language):
    """
    Gets the file extension for the given programming language.
    """
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

def get_language(file_paths):
    """
    Retrieves the programming language based on the main file's extension.
    """
    main_file_path = get_main_file(file_paths)
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


def get_main_file(file_paths):
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

def contains_gui_or_html_code(scripts):
    """
    Checks if any of the scripts contain GUI or HTML code.
    """
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

def clean_query(query):
    """
    Cleans the query string by removing URLs, file paths, and extensions.

    Args:
        query (str): The raw query string.

    Returns:
        str: A cleaned, more meaningful query string.
    """
    # Remove URLs
    query = re.sub(r'https?://\S+', '', query)
    # Remove file paths
    query = os.path.basename(query)
    # Remove file extensions
    query = os.path.splitext(query)[0]
    # Replace underscores and hyphens with spaces
    query = query.replace('_', ' ').replace('-', ' ')
    # Trim whitespace
    query = query.strip()
    return query


def process_html_content(html_content):
    """
    Parses the HTML content, finds all <img> tags, fetches images from Flickr,
    replaces the src attributes.

    Args:
        html_content (str): The raw HTML content.

    Returns:
        str: The modified HTML content with updated image sources.
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    # Find all <img> tags
    img_tags = soup.find_all('img')

    for img in img_tags:
        # Try to get a meaningful query
        query = img.get('alt') or img.get('src') or 'fitness'

        # Clean the query
        query = clean_query(query)

        # Fetch image data from Flickr
        image_data = fetch_flickr_image_data(query)

        if image_data:
            # Replace the src attribute
            img['src'] = image_data['image_url']
        else:
            logging.error(f"Failed to fetch image for query '{query}'")
            # Set a placeholder image or handle as needed
            img['src'] = 'https://via.placeholder.com/150'
            img['alt'] = 'Image not available'

    # Return the modified HTML content
    return str(soup)

def fetch_flickr_image_data(query):
    """
    Fetches image data from Flickr based on the search query.

    Args:
        query (str): The search query.

    Returns:
        dict: A dictionary containing image URL, or None if failed.
    """
    try:
        # Search for photos on Flickr
        photos = flickr.photos.search(
            text=query,
            per_page=1,
            sort='relevance',
            extras='url_c'  # Get medium-sized URL
        )

        if photos['photos']['photo']:
            photo = photos['photos']['photo'][0]
            image_url = photo.get('url_c')  # Medium-sized image
            if image_url:
                return {
                    'image_url': image_url
                }
            else:
                logging.error("No image URL available for the fetched photo.")
        else:
            logging.error(f"No photos found on Flickr for query '{query}'")
    except Exception as e:
        logging.error(f"Error fetching image from Flickr: {e}")
    return None

def display_html_file(file_name=None):
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
        main_file_path = get_main_file(file_paths)
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
        ext = ext.lower()
        if ext == '.html':
            # Process the HTML content to replace image sources
            processed_content = process_html_content(content)
            # Embed and process linked CSS and JS
            soup = BeautifulSoup(processed_content, 'html.parser')

            # Process linked CSS files
            for link in soup.find_all('link', rel='stylesheet'):
                href = link.get('href')
                if href:
                    css_path = file_paths.get(href)
                    if css_path and os.path.exists(css_path):
                        with open(css_path, 'r') as f_css:
                            css_content = f_css.read()
                        processed_css = process_css_content(css_content)
                        # Create a <style> tag with processed CSS
                        style_tag = soup.new_tag('style')
                        style_tag.string = processed_css
                        link.replace_with(style_tag)
                    else:
                        logging.error(f"CSS file '{href}' not found.")

            # Process linked JS files
            for script in soup.find_all('script', src=True):
                src = script.get('src')
                if src:
                    js_path = file_paths.get(src)
                    if js_path and os.path.exists(js_path):
                        with open(js_path, 'r') as f_js:
                            js_content = f_js.read()
                        processed_js = process_js_content(js_content)
                        # Create a <script> tag with processed JS
                        script_tag = soup.new_tag('script')
                        script_tag.string = processed_js
                        script.replace_with(script_tag)
                    else:
                        logging.error(f"JavaScript file '{src}' not found.")

            # Emit the modified HTML content
            final_content = str(soup)
            socketio.emit('html_output', {'content': final_content}, namespace='/terminal')
        else:
            socketio.emit('message', {'type': 'output', 'output': content}, namespace='/terminal')
        logging.debug(f"Emitted content of '{main_file_path}' to frontend.")
    except Exception as e:
        logging.error(f"Failed to read file '{main_file_path}': {e}")
        socketio.emit('message', {
            'type': 'error',
            'output': f"❌ Failed to read file '{main_file_path}': {e}\r\n"
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
        scripts = get_all_scripts(file_paths)
        fix_scripts_and_retry(scripts, terminal_output, retry_attempt + 1, screenshot_path)

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
            model="gpt-4",
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
                with open(file_path, 'r+') as f:
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
        from execution import execute_command  # Ensure proper import
        socketio.start_background_task(execute_command, testing_commands_list)

    except openai.error.OpenAIError as e:
        logging.error(f"OpenAI API error during script fixing: {e}")
        socketio.emit('message', {
            'type': 'error',
            'output': f"❌ OpenAI API error during script fixing: {e}\r\n"
        }, namespace='/terminal')
def process_css_content(css_content):
    """
    Parses the CSS content, finds all url() references, fetches images from Flickr,
    and replaces the url() values.
    """
    def replace_url(match):
        url = match.group(1).strip('\'"')
        query = clean_query(url)
        image_data = fetch_flickr_image_data(query)
        if image_data:
            return f"url('{image_data['image_url']}')"
        else:
            logging.error(f"Failed to fetch image for query '{query}'")
            return f"url('https://via.placeholder.com/150')"
    
    # Regex to find url() references
    css_content = re.sub(r'url\(([^)]+)\)', replace_url, css_content)
    return css_content
def process_js_content(js_content):
    """
    Parses the JavaScript content, finds image URL assignments, fetches images from Flickr,
    and replaces the URLs.
    """
    # Regex to find assignments like hero.style.backgroundImage = 'url("image.jpg")';
    pattern = re.compile(r'(backgroundImage\s*=\s*[\'"]url\(([^)]+)\)[\'"])')
    
    def replace_background_image(match):
        full_match = match.group(1)
        url = match.group(2).strip('\'"')
        query = clean_query(url)
        image_data = fetch_flickr_image_data(query)
        if image_data:
            return f'backgroundImage = \'url("{image_data["image_url"]}")\''
        else:
            logging.error(f"Failed to fetch image for query '{query}'")
            return f'backgroundImage = \'url("https://via.placeholder.com/150")\''
    
    js_content = pattern.sub(replace_background_image, js_content)
    return js_content
def fetch_and_save_image(query, filename):
    """
    Fetches an image from Flickr based on the query and saves it locally.

    Args:
        query (str): The search query.
        filename (str): The filename to save the image as.

    Returns:
        bool: True if successful, False otherwise.
    """
    image_data = fetch_flickr_image_data(query)
    if image_data:
        image_url = image_data['image_url']
        response = requests.get(image_url)
        if response.status_code == 200:
            # Ensure the 'static' directory exists
            if not os.path.exists('static'):
                os.makedirs('static')
            image_path = os.path.join('static', filename)
            with open(image_path, 'wb') as f:
                f.write(response.content)
            return True
        else:
            logging.error(f"Failed to download image from '{image_url}'")
    else:
        logging.error(f"Failed to fetch image data for query '{query}'")
    return False

def fetch_flickr_image_data(query):
    """
    Fetches image data from Flickr based on the search query.

    Args:
        query (str): The search query.

    Returns:
        dict: A dictionary containing image URL, or None if failed.
    """
    try:
        # Search for photos on Flickr
        photos = flickr.photos.search(
            text=query,
            per_page=1,
            sort='relevance',
            extras='url_c'  # Get medium-sized URL
        )

        if photos['photos']['photo']:
            photo = photos['photos']['photo'][0]
            image_url = photo.get('url_c')  # Medium-sized image
            if image_url:
                return {
                    'image_url': image_url
                }
            else:
                logging.error("No image URL available for the fetched photo.")
        else:
            logging.error(f"No photos found on Flickr for query '{query}'")
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
