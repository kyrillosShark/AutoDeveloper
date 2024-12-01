# AutoDeveloper

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


https://github.com/user-attachments/assets/3ff72a18-14eb-4caa-b146-6bfa8f03c218


*Coming soon…*

## Installation

### Prerequisites

- **Python 3.7+**: Ensure Python is installed on your system. You can download it from [here](https://www.python.org/downloads/).
- **pip Package Manager**: Python’s package installer. It typically comes bundled with Python. Verify by running:

  ```bash
  pip --version

	•	Git: To clone the repository. Install Git from here if not already installed.

Clone the Repository

git clone https://github.com/kyrillosShark/Autodeveloper.git
cd AutoDeveloper

Install Dependencies

It’s recommended to use a virtual environment to manage dependencies.
	1.	Create a Virtual Environment

python3 -m venv venv


	2.	Activate the Virtual Environment
	•	On Windows:

venv\Scripts\activate


	•	On macOS and Linux:

source venv/bin/activate


	3.	Install Required Packages

pip install -r requirements.txt



Set Up Environment Variables

Create a .env file in the root directory of the project and add the following variables:

OPENAI_API_KEY=your_openai_api_key
FLICKR_API_KEY=your_flickr_api_key
SECRET_KEY=your_secret_key
DEBUG=True

	•	OPENAI_API_KEY: Your OpenAI API key for accessing GPT models.
	•	FLICKR_API_KEY: Your Flickr API key for image integration.
	•	SECRET_KEY: A secret key for securing sessions and other cryptographic components.
	•	DEBUG: Set to False in a production environment.

Additional Setup

	•	Database Migration
If the application uses a database (e.g., SQLite, PostgreSQL), run the necessary migrations:

python manage.py migrate


	•	Static Files Collection
Collect static files for the web interface:

python manage.py collectstatic


	•	API Key Setup
Ensure that the API keys provided in the .env file have the necessary permissions and are active.

Usage

Running the Application

	1.	Activate the Virtual Environment
Ensure your virtual environment is active. If not, activate it using:
	•	On Windows:

venv\Scripts\activate


	•	On macOS and Linux:

source venv/bin/activate


	2.	Start the Development Server

python app.py

The application should now be running at http://localhost:5000/ by default.

Using the Web Interface

	1.	Access the Application
Open your web browser and navigate to http://localhost:5000/.
	2.	Generate Code
	•	Enter a project description or prompt in the provided text area.
	•	Select the desired programming language from the dropdown menu.
	•	Click the Generate Code button.
	3.	View and Execute Code
	•	The generated code will be displayed in the code editor.
	•	Review the code and make any necessary adjustments.
	•	Click the Execute button to run the code.
	•	The output, errors, and any relevant screenshots will be displayed below the editor.
	4.	Assess and Auto-Fix
	•	If the execution fails, the application will attempt to assess the error.
	•	It will automatically try to fix the code and re-execute.
	•	The results of each attempt will be displayed for your review.

Configuration

Configuration settings can be adjusted in the .env file or within the config.py file (if applicable). Key configurations include:
	•	API Keys: OPENAI_API_KEY, FLICKR_API_KEY
	•	Application Settings: DEBUG, SECRET_KEY
	•	Database Settings: Configure database URI and credentials.
	•	Execution Settings: Timeouts, resource limits for code execution.

Ensure that sensitive information like API keys and secret keys are kept secure and not exposed in version control systems.

API Endpoints

POST /generate_code

Generates code based on the provided project description and programming language.

Request Body

{
  "description": "A detailed description of the project or functionality you want to implement.",
  "language": "python"
}

	•	description: (string) A comprehensive description of the desired project or feature.
	•	language: (string) The programming language for the generated code (e.g., python, cpp, c, html).

Response

{
  "status": "success",
  "code": "def hello_world():\n    print('Hello, World!')",
  "language": "python",
  "message": "Code generated successfully."
}

	•	status: (string) Indicates the success or failure of the request.
	•	code: (string) The generated code based on the description.
	•	language: (string) The programming language of the generated code.
	•	message: (string) Additional information about the request status.

In case of an error:

{
  "status": "error",
  "message": "Invalid programming language specified."
}

	•	status: (string) Indicates the success or failure of the request.
	•	message: (string) Details about the error encountered.

## File Structure

AutoDeveloper/
├── app.py
├── config.py
├── requirements.txt
├── .env
├── README.md
├── templates/
│   └── index.html
├── static/
│   ├── css/
│   ├── js/
│   └── images/
├── api/
│   ├── init.py
│   └── routes.py
├── generators/
│   ├── init.py
│   └── code_generator.py
├── executors/
│   ├── init.py
│   └── code_executor.py
├── assessments/
│   ├── init.py
│   └── code_assessor.py
└── utils/
├── init.py
└── helpers.py

### File Explanations

- **app.py**: The main entry point of the application. Initializes the web server and routes.
- **config.py**: Contains configuration settings loaded from environment variables.
- **requirements.txt**: Lists all Python dependencies required to run the application.
- **.env**: Stores environment variables such as API keys and secret configurations.
- **README.md**: Documentation for the project.
- **templates/**: Contains HTML templates for the web interface.
  - **index.html**: The main webpage where users interact with the application.
- **static/**: Holds static assets like CSS, JavaScript, and images.
  - **css/**: Stylesheets for the web interface.
  - **js/**: JavaScript files for frontend functionality.
  - **images/**: Static images used in the application.
- **api/**: Contains API-related modules.
  - **routes.py**: Defines the API endpoints.
- **generators/**: Modules responsible for generating code using AI models.
  - **code_generator.py**: Handles interactions with OpenAI’s GPT models to generate code.
- **executors/**: Modules responsible for executing the generated code.
  - **code_executor.py**: Executes the code in a secure and sandboxed environment.
- **assessments/**: Modules for assessing the execution results.
  - **code_assessor.py**: Evaluates the output and determines if the execution was successful.
- **utils/**: Utility modules for helper functions and common tasks.
  - **helpers.py**: Contains helper functions used across different modules.

## Dependencies

The project relies on the following major dependencies:

- **Flask**: A lightweight WSGI web application framework for Python.
- **OpenAI**: For accessing GPT models to generate code.
- **Flickr API**: To fetch images for enhancing HTML content.
- **Docker**: (Optional) For containerizing the application and executing code in isolated environments.
- **SQLAlchemy**: For database interactions if a relational database is used.
- **Requests**: To handle HTTP requests to external APIs.
- **dotenv**: To load environment variables from the `.env` file.
- **Jinja2**: For HTML templating in Flask.
- **Bootstrap**: For responsive and mobile-first front-end web development.

Refer to the `requirements.txt` file for the complete list of dependencies and their respective versions.

## Contributing

Contributions are welcome! Please follow these guidelines to contribute to the project:

1. **Fork the Repository**

   Click the **Fork** button at the top-right corner of the repository page to create your own fork.

2. **Clone Your Fork**

   ```bash
   git clone https://github.com/your_username/Autodeveloper.git
   cd AutoDeveloper

	3.	Create a New Branch

git checkout -b feature/YourFeatureName


	4.	Make Changes
Implement your feature or fix bugs. Ensure that your code follows the project’s coding standards and guidelines.
	5.	Commit Your Changes

git add .
git commit -m "Add feature: YourFeatureName"


	6.	Push to Your Fork

git push origin feature/YourFeatureName


	7.	Create a Pull Request
Navigate to the original repository and create a pull request from your fork. Provide a clear description of the changes and the purpose behind them.

Code of Conduct

Please adhere to the Code of Conduct when contributing to this project.

License

This project is licensed under the MIT License. You are free to use, modify, and distribute this software in accordance with the terms of the license.

Acknowledgements

	•	OpenAI: For providing the powerful GPT models that enable AI-driven code generation.
	•	Flask: The web framework that powers the backend of this application.
	•	Bootstrap: For the responsive and sleek design of the web interface.
	•	Flickr: For the rich repository of images used to enhance HTML content.
	•	Contributors and Community: Special thanks to all contributors and the developer community for their support and feedback.

This project is a culmination of collaborative efforts and the integration of cutting-edge technologies to simplify and enhance the coding experience.

