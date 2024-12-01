# execution.py

import subprocess
import threading
import queue
import os
import sys
import tempfile
import logging
import base64
import re

from typing import Dict, List
from app import socketio
from config import PROMPT, MAX_ATTEMPTS
from helpers import (
    normalize_newlines,
    get_language,
    get_main_file,
    get_all_scripts,
    contains_gui_or_html_code,
    capture_screenshot,
    fix_scripts_and_retry,
    emit_assessment_result,
    display_html_file
    
)
from file_manager import file_paths

from flask_socketio import emit


testing_commands_list = []
process = None
input_queue = queue.Queue()
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


def start_execution_process(language):
    global process, input_queue

    if language == 'python':
        main_file = get_main_file(file_paths)
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

def terminate_process():
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

def execute_command(commands=None):
    """
    Executes the main script or a list of testing commands and handles output.
    """
    from code_generation import retry_attempt
    if commands is None:
        # Existing code for executing the main program
        language = get_language(file_paths)
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
            display_html_file()
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
                if contains_gui_or_html_code(get_all_scripts(file_paths)):
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
                scripts = get_all_scripts(file_paths)
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
        # Execute the list of testing commands
        combined_output = ""  # Initialize combined output

        for cmd in commands:
            # Emit the command to the terminal before execution
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

                # Handle GUI output after command execution
                if contains_gui_or_html_code(get_all_scripts(file_paths)):
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
        scripts = get_all_scripts(file_paths)
        assessment_result = evaluate_execution(scripts, combined_output)

        # Emit the assessment result and handle retry if necessary
        emit_assessment_result(assessment_result, combined_output)
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


def get_all_scripts(file_paths):
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
            # Handle error appropriately
    return scripts
