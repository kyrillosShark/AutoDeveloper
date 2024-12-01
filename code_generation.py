# code_generation.py

import subprocess
import tiktoken
import openai
import logging
import pyautogui
import json
import re
import os
import tempfile
from app import socketio

from typing import Dict, List
from app import socketio
from flask import request, jsonify
from config import MAX_PROMPT_TOKENS, MAX_ATTEMPTS, OPENAI_API_KEY
from helpers import (
    extract_code,
    parse_testing_commands,
    strip_code_fences,
    get_extension,
    get_language_from_extension,
    normalize_newlines,
    parse_fixed_scripts,
)
from file_manager import (
    create_file,
    save_generated_code,
    file_paths,
)
from execution import execute_command
from flask import request, jsonify
from flask_socketio import emit
from app import app
openai.api_key = OPENAI_API_KEY

global original_prompt
testing_commands_list = []
retry_attempt = 1

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
            model="gpt-4",
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
                    f"Please provide only the complete code for '{file_name}' in {language_for_file} based on the following project description.\n\n"
                    f"Do not include any explanations, comments, code fences, markdown, or any extra text.\n\n"
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
                        {"role": "user", "content":  f"You are a professional {language_for_file} developer who writes clean, well-structured code without any additional text or comments. Provide only the code, nothing else."+code_prompt}
                    ],
                    #max_tokens=2000,  # Adjust as needed
                    #temperature=0.2,
                    stream=True
                     # Enable streaming
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
                model="gpt-4",
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

def estimate_tokens(text, model="gpt-4"):
    """
    Estimates the number of tokens in the text for the specified model.
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")  # Fallback encoding
    return len(encoding.encode(text))
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
