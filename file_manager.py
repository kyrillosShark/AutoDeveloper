# file_manager.py
import os
import tempfile
import logging
from helpers import is_valid_file_name
from config import file_paths
from typing import Dict, List

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

def save_generated_code(file_name, content):
    """
    Saves the generated code to the specified file.
    """
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

def save_file(file_name, content):
    """
    Saves content to the specified file.
    """
    file_path = file_paths.get(file_name)
    if not file_path:
        logging.error(f"File path for '{file_name}' not found.")
        return False

    try:
        with open(file_path, 'w') as f:
            f.write(content)
        logging.debug(f"File '{file_name}' saved.")
        return True
    except Exception as e:
        logging.error(f"Failed to save file '{file_name}': {e}")
        return False

def delete_file(file_name):
    """
    Deletes the specified file.
    """
    if file_name not in file_paths:
        logging.error(f"File '{file_name}' not found.")
        return False

    file_path = file_paths[file_name]
    try:
        os.remove(file_path)
        del file_paths[file_name]
        logging.debug(f"File '{file_name}' deleted.")
        return True
    except Exception as e:
        logging.error(f"Failed to delete file '{file_name}': {e}")
        return False
