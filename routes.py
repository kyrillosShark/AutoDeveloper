# routes.py
import subprocess
from app import socketio
from flask import request, jsonify, render_template
from app import app
from file_manager import create_file, save_file, delete_file, file_paths
from code_generation import generate_code_route
from helpers import is_valid_file_name
import logging
import os
import tempfile
import shutil
import json
from config import file_paths


@app.route('/')
def index():
    # Create the default 'main.py' file
    status, message = create_file('main.py')
    if not status:
        logging.error(f"Failed to create default file: {message}")
        return "Failed to initialize session.", 500
    return render_template('index.html')  # Ensure you have an index.html template

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