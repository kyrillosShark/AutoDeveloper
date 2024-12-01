# AI Code Generator and Executor

An AI-powered web application that generates, executes, and assesses code based on user-provided project descriptions. Leveraging OpenAI’s GPT models, this application supports multiple programming languages and provides an interactive interface for seamless code generation and execution.

## Table of Contents

- [Features](#features)
- [Demo](#demo)
- [Installation](#installation)
  - [Prerequisites](#prerequisites)
  - [Clone the Repository](#clone-the-repository)
  - [Install Dependencies](#install-dependencies)
  - [Set Up Environment Variables](#set-up-environment-variables)
  - [Additional Setup](#additional-setup)
- [Usage](#usage)
  - [Running the Application](#running-the-application)
  - [Using the Web Interface](#using-the-web-interface)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
  - [`POST /generate_code`](#post-generate_code)
    - [Request Body](#request-body)
    - [Response](#response)
- [File Structure](#file-structure)
  - [File Explanations](#file-explanations)
- [Dependencies](#dependencies)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)

## Features

- **AI-Powered Code Generation**: Generate code in multiple programming languages based on user-provided prompts using OpenAI’s GPT models.
- **Multi-Language Support**: Supports Python, C++, C, HTML, and more.
- **Automated File Handling**: Determines necessary files and scripts, creates them, and manages file operations.
- **Code Execution and Output Capture**: Executes generated code, captures outputs, errors, and GUI screenshots if applicable.
- **Execution Assessment and Auto-Fixing**: Assesses code execution success and attempts to fix and retry code execution if it fails.
- **Web Interface**: Provides a user-friendly web interface for interaction and display of results.
- **Image Integration with Flickr API**: Fetches images from Flickr to enhance HTML content.

## Demo

*Coming soon…*

## Installation

### Prerequisites

- Python 3.7+
- pip package manager

### Clone the Repository

```bash
git clone https://github.com/kyrillosShark/Autodeveloper.git
cd AutoDeveloper
