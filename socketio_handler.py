# socketio_handlers.py

from app import socketio
from flask_socketio import emit
from flask import request
import logging
from execution import execute_command, terminate_process, input_queue, process
from code_generation import execute_command
from config import PROMPT
from helpers import normalize_newlines
from execution import display_html_file
import re
import shlex

socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False, ping_timeout=120, ping_interval=25)

@socketio.on('connect', namespace='/terminal')
def handle_connect():
    logging.debug("A client connected to /terminal namespace.")
    emit('message', {
        'type': 'system',
        'output': 'Connected to terminal.\r\n'
    })
    emit('message', {'type': 'prompt', 'output': PROMPT})


@socketio.on('display_html', namespace='/terminal')
def handle_display_html(data):
    file_name = data.get('file_name')
    if file_name:
        display_file(file_name)

@socketio.on('execute', namespace='/terminal')
def execute_command_event():
    
    """
    Executes the main script.
    """
    socketio.start_background_task(execute_command)


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

@socketio.on('display_html', namespace='/terminal')
def handle_display_html(data):
    file_name = data.get('file_name')
    if file_name:
        display_html_file(file_name)

# Add other event handlers as needed

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