 /********************************************************************
 * SECTION 1: Initialize Ace Editor
 * ---------------------------------------------------------------
 * Sets up the Ace Editor with the desired theme, mode, and settings.
 ********************************************************************/
var editor = ace.edit("editor");
editor.setTheme("ace/theme/monokai");
editor.session.setMode("ace/mode/python");
editor.setReadOnly(false); // Allow manual edits

/********************************************************************
 * SECTION 2: Initialize Variables
 * ---------------------------------------------------------------
 * Declares and initializes all global variables and DOM element references.
 ********************************************************************/
var currentFileName = 'main.py'; // Default file name

// Event Listener References will be initialized inside DOMContentLoaded
var miloPrompt;
var automateButton;
var newTabButton;
var runButton;
var tabsDiv;
var loadingSpinner;
var sideMenu;

// Initialize typing counter and pending GUI data
let typingCounter = 0;
let pendingGUIData = null;
let testingCommands = [];

var mainContent;

// Initialize Terminal and Socket.IO
var term = null; // xterm.js Terminal instance (single instance)
var socket = null; // Socket.IO client
var currentCommand = ''; // To track user input after the prompt
const PROMPT = '$user@milo ';

// Map to store editor content for each file
var fileContents = {};

// Map to store code chunks for each file
var codeChunks = {};

/********************************************************************
 * SECTION 3: DOM Content Loaded Event
 * ---------------------------------------------------------------
 * Initializes the default tab and terminal once the DOM is fully loaded.
 ********************************************************************/
document.addEventListener('DOMContentLoaded', function () {
    // Initialize DOM Elements
    sideMenu = document.getElementById('side-menu');
    sideMenuToggle = document.getElementById('side-menu-toggle');
    mainContent = document.querySelector('main');
    miloPrompt = document.getElementById('milo-prompt');
    automateButton = document.getElementById('automateButton');
    newTabButton = document.getElementById('newTabButton');
    runButton = document.getElementById('runButton');
    tabsDiv = document.getElementById('tabs');
    loadingSpinner = document.getElementById('loading-spinner');

    // Panels Toggle Buttons (Assuming these panels exist)
    var lintToggleButton = document.getElementById('lint-toggle-button');
    var versionHistoryButton = document.getElementById('version-history-button');
    var collaboratorsToggleButton = document.getElementById('collaborators-toggle-button');
    

    // Toggle Side Menu
    sideMenuToggle.addEventListener('click', function(event) {
        event.stopPropagation(); // Prevent event from bubbling up
        toggleSideMenu();
    });

    // Function to toggle side menu
    function toggleSideMenu() {
        if (sideMenu.classList.contains('open')) {
            sideMenu.classList.remove('open');
            sideMenu.classList.add('hidden');
            mainContent.classList.remove('shifted');
        } else {
            sideMenu.classList.remove('hidden');
            sideMenu.classList.add('open');
            mainContent.classList.add('shifted');
        }
    }

    // Close the side menu when clicking outside of it
    document.addEventListener('click', function(event) {
        if (!sideMenu.contains(event.target) && !sideMenuToggle.contains(event.target)) {
            if (sideMenu.classList.contains('open')) {
                toggleSideMenu();
            }
        }
    });

    // Prevent clicks inside the side menu from closing it
    sideMenu.addEventListener('click', function(e) {
        e.stopPropagation();
    });

    // Ensure side menu is hidden on initial load
    sideMenu.classList.add('hidden');

    // Handle Automate Button inside Side Menu
    // Handle Automate Button inside Side Menu
if (automateButton) {
  automateButton.addEventListener('click', function () {
      const prompt = miloPrompt.value.trim();
      if (!prompt) {
          alert('Please enter a prompt for Milo.');
          return;
      }

      // Disable the Automate button to prevent multiple clicks
      automateButton.disabled = true;

      // Reset codeChunks and testingCommands
      codeChunks = {};
      testingCommands = [];

      // Show loading spinner
      showLoading();

      // Show editor loading overlay
      showEditorLoadingOverlay();

      // Indicate that code generation is in progress
      isCodeGenerationInProgress = true;

      // Send the prompt to the server to generate code
      fetch('/generate_code', {
          method: 'POST',
          headers: {
              'Content-Type': 'application/json',
          },
          body: JSON.stringify({
              prompt: prompt,
              language: document.getElementById('language').value,
          }),
      })
          .then((response) => response.json())
          .then((data) => {
              if (data.error) {
                  appendToConsole(`Error: ${data.error}\n`, 'error');
                  hideLoading();
                  hideEditorLoadingOverlay();
                  automateButton.disabled = false;
                  isCodeGenerationInProgress = false;
                  return;
              }

              // The backend emits 'create_tab' and 'code_generation_complete' events
              // for each file. We handle them in the Socket.IO event handlers.
          })
          .catch((error) => {
              appendToConsole(`Error: ${error}\n`, 'error');
              hideLoading();
              hideEditorLoadingOverlay();
              automateButton.disabled = false;
              isCodeGenerationInProgress = false;
          });
  });
} else {
  console.warn("Element with id 'automateButton' not found.");
}


    if (newTabButton) {
        newTabButton.addEventListener('click', function () {
            var fileName = prompt(
                'Enter new file name (e.g., script.py or program.cpp):',
                'new_file.py'
            );
            if (fileName) {
                if (!isValidFileName(fileName)) {
                    alert(
                        'Invalid file name. Only letters, numbers, underscores, hyphens, and dots are allowed.'
                    );
                    return;
                }
                createNewTab(fileName)
                    .then(() => {
                        console.log(`New tab for '${fileName}' created successfully.`);
                    })
                    .catch((error) => {
                        console.error(
                            `Failed to create new tab for '${fileName}': ${error.message}`
                        );
                        alert(
                            `Failed to create new tab for '${fileName}': ${error.message}`
                        );
                    });
            }
        });
    } else {
        console.warn("Element with id 'newTabButton' not found.");
    }

    if (runButton) {
        runButton.addEventListener('click', function () {
            runCode();
        });
    } else {
        console.warn("Element with id 'runButton' not found.");
    }

    // Initialize Language Selection Change Handler
    var languageSelector = document.getElementById('language');
    if (languageSelector) {
        languageSelector.addEventListener('change', function () {
            var language = this.value;
            var mode = 'python';
            if (language === 'python') {
                mode = 'python';
            } else if (language === 'c++' || language === 'c') {
                mode = 'c_cpp';
            } else if (language === 'html') {
                mode = 'html';
            } else if (language === 'javascript') {
                mode = 'javascript';
            }
            editor.session.setMode('ace/mode/' + mode);
            // Update file extension based on language
            var extensionMap = {
                python: 'py',
                'c++': 'cpp',
                html: 'html',
                javascript: 'js',
            };
            var newFileName = 'main.' + extensionMap[language];
            var activeTab = document.querySelector(
                `.tab[data-file-name="${newFileName}"]`
            );
            if (activeTab) {
                switchToTab(newFileName);
            } else {
                // If the tab doesn't exist, create a new one
                createNewTab(newFileName)
                    .then(() => {
                        console.log(`Switched to new file '${newFileName}'.`);
                    })
                    .catch((error) => {
                        console.error(
                            `Failed to create or switch to file '${newFileName}': ${error.message}`
                        );
                        alert(
                            `Failed to create or switch to file '${newFileName}': ${error.message}`
                        );
                    });
            }
        });
    } else {
        console.warn("Element with id 'language' not found.");
    }

    // Initialize the default tab and terminal
    var defaultFileName = 'main.py';

    createNewTab(defaultFileName)
        .then(() => {
            console.log(
                `Default file '${defaultFileName}' created or already exists.`
            );
            initializeTerminal(); // Initialize terminal after DOM is loaded
        })
        .catch((error) => {
            console.error(
                `Failed to initialize default file '${defaultFileName}': ${error.message}`
            );
            alert(
                `Failed to initialize default file '${defaultFileName}': ${error.message}`
            );
            initializeTerminal(); // Attempt to initialize the terminal anyway
        });

    // Initialize Additional UI Components (e.g., Theme Toggle, Share Button, Modal)
    // Example: Initialize Theme Toggle
    var themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('change', function () {
            if (this.checked) {
                document.documentElement.classList.add('dark');
                editor.setTheme('ace/theme/github');
            } else {
                document.documentElement.classList.remove('dark');
                editor.setTheme('ace/theme/monokai');
            }
        });
    } else {
        console.warn("Element with id 'theme-toggle' not found.");
    }

    // Example: Initialize Share Button
    var shareButton = document.getElementById('share-button');
    if (shareButton) {
        shareButton.addEventListener('click', function () {
            // The share modal is handled by Bootstrap, so no need for JS here
            console.log('Share button clicked. Share modal will be displayed.');
        });
    } else {
        console.warn("Element with id 'share-button' not found.");
    }

    // Initialize Panels Toggle Buttons (Assuming these panels exist)
    if (lintToggleButton) {
        lintToggleButton.addEventListener('click', function () {
            togglePanel('lint-panel');
        });
    } else {
        console.warn("Element with id 'lint-toggle-button' not found.");
    }

    if (versionHistoryButton) {
        versionHistoryButton.addEventListener('click', function () {
            togglePanel('version-history-panel');
        });
    } else {
        console.warn("Element with id 'version-history-button' not found.");
    }

    if (collaboratorsToggleButton) {
        collaboratorsToggleButton.addEventListener('click', function () {
            togglePanel('collaborators-panel');
        });
    } else {
        console.warn("Element with id 'collaborators-toggle-button' not found.");
    }

    // Initialize Share Link Copy Functionality
    var copyShareLinkButton = document.getElementById('copy-share-link');
    if (copyShareLinkButton) {
        copyShareLinkButton.addEventListener('click', function () {
            var shareLink = document.getElementById('share-link');
            if (shareLink) {
                shareLink.select();
                shareLink.setSelectionRange(0, 99999); // For mobile devices
                navigator.clipboard
                    .writeText(shareLink.value)
                    .then(() => {
                        alert('Share link copied to clipboard!');
                    })
                    .catch((err) => {
                        console.error('Failed to copy: ', err);
                    });
            }
        });
    } else {
        console.warn("Element with id 'copy-share-link' not found.");
    }

    // Initialize Tabs Click Handler
    tabsDiv.addEventListener('click', function (e) {
        if (e.target.classList.contains('close-btn')) {
            var tab = e.target.parentElement;
            var fileName = tab.getAttribute('data-file-name');
            closeTab(fileName);
        } else {
            var clickedTab = e.target.closest('.tab');
            if (clickedTab) {
                var fileName = clickedTab.getAttribute('data-file-name');
                switchToTab(fileName);
            }
        }
    });

    // Initialize Split.js for resizable panes
    Split(['#editor-container', '#panels-container'], {
        sizes: [70, 30], // Adjust initial sizes as needed
        minSize: 200, // Minimum size in pixels
        gutterSize: 5,
        cursor: 'col-resize',
        direction: 'horizontal',
    });

    // Initialize Split.js for panels split: output and terminal
    Split(['#output-panel', '#terminal-panel'], {
        sizes: [50, 50], // Equal initial sizes
        minSize: 100,
        gutterSize: 5,
        cursor: 'row-resize',
        direction: 'vertical',
    });

    // Initialize Interact.js for drag-and-drop rearrangement
    initializeDragAndDrop();

    /********************************************************************
     * SECTION 4: Initialize Download Executable Button
     * ---------------------------------------------------------------
     * Sets up the event listener for the Download Executable button,
     * handling the download process with proper error handling and user feedback.
     ********************************************************************/
    const downloadExecutableButton = document.getElementById('downloadExecutableButton');

    if (downloadExecutableButton) {
        downloadExecutableButton.addEventListener('click', function () {
            // Disable the button to prevent multiple clicks
            downloadExecutableButton.disabled = true;

            // Show loading spinner
            showLoading();

            // Prepare data to send to the backend
            const data = {
                file_name: currentFileName,
                code: editor.getValue(),
                language: getLanguageFromFileName(currentFileName)
            };

            // Validate language before proceeding
            if (data.language === 'unknown') {
                appendToConsole('Error: Unsupported language for packaging.\n', 'error');
                hideLoading();
                downloadExecutableButton.disabled = false;
                return;
            }

            // Send POST request to backend to package the executable
            fetch('/package_executable', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data),
            })
            .then(response => {
                if (!response.ok) {
                    // Attempt to extract error message from response
                    return response.json().then(errData => {
                        const errorMessage = errData.error || 'Failed to package the executable.';
                        throw new Error(errorMessage);
                    });
                }
                // Extract the Content-Disposition header
                const disposition = response.headers.get('Content-Disposition');
                return response.blob().then(blob => ({ blob, disposition }));
            })
            .then(({ blob, disposition }) => {
                // Create a URL for the blob
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;

                // Extract filename from Content-Disposition or use default
                let filename = 'executable.zip'; // Default filename
                if (disposition && disposition.indexOf('attachment') !== -1) {
                    const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
                    const matches = filenameRegex.exec(disposition);
                    if (matches != null && matches[1]) { 
                        filename = matches[1].replace(/['"]/g, '');
                    }
                }
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);

                appendToConsole(`Executable downloaded successfully as ${filename}.\n`, 'system');
            })
            .catch(error => {
                appendToConsole(`Error: ${error.message}\n`, 'error');
            })
            .finally(() => {
                // Hide loading spinner and re-enable the button
                hideLoading();
                downloadExecutableButton.disabled = false;
            });
        });
    } else {
        console.warn("Element with id 'downloadExecutableButton' not found.");
    }
});

/********************************************************************
 * SECTION 4: Initialize Terminal and Socket.IO
 * ---------------------------------------------------------------
 * Sets up the terminal interface using xterm.js and establishes a
 * Socket.IO connection for real-time communication.
 ********************************************************************/
function initializeTerminal() {
    // Prevent multiple initializations
    if (term && socket) {
        console.log('Terminal and Socket.IO are already initialized.');
        return;
    }

    // Initialize xterm.js Terminal
    term = new Terminal({
        cursorBlink: true,
        rows: 20,
        cols: 80,
        theme: {
            foreground: '#FFFFFF',
        },
    });
    term.open(document.getElementById('terminal-container'));

    // Initialize Socket.IO
    socket = io('/terminal', {
        // Ensure this matches the backend namespace
        transports: ['websocket'],
        path: '/socket.io',
    });

    // Handle connection events
    socket.on('connect', function () {
        console.log('Socket.IO connected');
    });

    // Handle messages from the server
    socket.on('message', function(data) {
        if (data.type === 'prompt') {
            console.log('Received prompt message from backend:', data.output);
            // The 'prompt' message indicates that command execution is complete
            // Handled in simulateTypingInTerminal's onMessage function
        } else if (data.type === 'output') {
            appendToConsole(data.output, 'output');
        } else if (data.type === 'error') {
            appendToConsole(data.output, 'error');
        } else if (data.type === 'system') {
            appendToConsole(data.output, 'system');
        }
    });

    // Handle 'code_chunk' events
    // Handle 'code_chunk' events
    socket.on('code_chunk', (data) => {
      console.log('Received code_chunk event:', data);
      const { chunk, file_name } = data;
  
      // Initialize code storage for the file if not already
      if (!codeChunks[file_name]) {
          codeChunks[file_name] = '';
      }
  
      // Append the received chunk
      codeChunks[file_name] += chunk;
  });
  

    // Handle 'code_generation_complete' event to hide overlays
    // Handle 'code_generation_complete' event to hide overlays
socket.on('code_generation_complete', function (data) {
  console.log("Received 'code_generation_complete' event:", data);
  const { file_name } = data;

  // Get the assembled code
  let fullCode = codeChunks[file_name];

  // Strip code fences from the assembled code
  fullCode = stripCodeFencing(fullCode);

  // Update the editor content
  updateEditorContent(file_name, fullCode);

  // Clean up
  delete codeChunks[file_name];

  // Indicate that code generation is complete
  isCodeGenerationInProgress = false;

  // Hide the loading overlays
  hideLoading();
  hideEditorLoadingOverlay();

  // Re-enable the Automate button
  if (automateButton) {
      automateButton.disabled = false;
  }
});

    // Handle 'create_tab' event from the backend to create empty tabs
    socket.on('create_tab', function (data) {
        console.log("Received 'create_tab' event:", data);
        const fileName = data.file_name;
        if (fileName) {
            createNewTab(fileName)
                .then(() => {
                    console.log(`Tab for file '${fileName}' created.`);
                })
                .catch((error) => {
                    appendToConsole(
                        `Error: Unable to create tab for '${fileName}'. ${error}\n`,
                        'error'
                    );
                });
        }
    });

    // Handle 'html_output' event from the backend
    socket.on('html_output', function (data) {
      var outputContainer = document.getElementById('output-container');
      console.log('Appending HTML output to:', outputContainer);
  
      if (!outputContainer) {
          console.error('Error: output-container element not found');
          return;
      }
  
      // Clear previous content
      outputContainer.innerHTML = '';
  
      // Create an iframe to display the HTML content securely
      var iframe = document.createElement('iframe');
      iframe.sandbox = 'allow-scripts'; // Adjust sandbox attributes as needed
      iframe.style.width = '100%';
      iframe.style.height = '100%';
      iframe.style.border = 'none';
      iframe.style.margin = '0';
      iframe.style.padding = '0';
      iframe.style.background = '#FFFFFF';
  
      // Write the HTML content into the iframe
      iframe.srcdoc = data.content;
  
      // Append the iframe to the output container
      outputContainer.appendChild(iframe);
  
      appendToConsole(
          'Displayed HTML content.\n',
          'system'
      );
  });
  
    // Handle 'image_output' event from the backend
    socket.on('image_output', function(data) {
        console.log('Received image_output event with GUI data.');
        pendingGUIData = data; // Store the GUI data

        // Check if typing is complete
        if (typingCounter === 0) {
            showGUI(pendingGUIData);
            appendToConsole('GUI is now displayed after typing completion.\n', 'system');
            pendingGUIData = null;
        } else {
            console.log('Typing is in progress. GUI will be displayed after typing is complete.');
        }
    });

    // Handle 'update_line' event from the backend
    socket.on('update_line', function(data) {
        const fileName = data.file_name;
        const lineNumber = data.line_number;
        const newCode = data.new_code;

        // Since we are using a single Ace Editor instance, ensure we're on the correct file
        if (fileName !== currentFileName) {
            // Optionally switch to the file or handle as needed
            console.warn(`Received update for file '${fileName}', but current file is '${currentFileName}'.`);
            return;
        }

        if (editor) {
            // Ace Editor uses zero-based indices for lines
            const index = lineNumber - 1;

            // Get the current line content
            const session = editor.getSession();
            const lineCount = session.getLength();

            if (index >= 0 && index < lineCount) {
                // Replace the line with new code
                session.replace({
                    start: { row: index, column: 0 },
                    end: { row: index, column: session.getLine(index).length }
                }, newCode);

                // Optionally, move the cursor to the updated line
                editor.gotoLine(lineNumber, 0, true);
            } else {
                console.warn(`Line number ${lineNumber} is out of range.`);
            }
        } else {
            console.error('Editor instance not initialized.');
        }
    });

    // Handle 'testing_commands' event
    socket.on('testing_commands', function(data) {
        console.log('Received testing commands:', data.commands);
        testingCommands = data.commands;
    });

    // Handle connection errors
    socket.on('connect_error', function (err) {
        console.error('Connection Error:', err);
        term.writeln('\r\nConnection Error. Please try again.\r\n');
    });

    socket.on('disconnect', function () {
        term.writeln('\r\nDisconnected from the terminal.\r\n');
    });

    // Capture user input in the terminal and handle prompt
    term.onData((e) => {
        switch (e) {
            case '\r': // Enter
                term.write('\r\n');
                if (currentCommand.trim().length > 0) {
                    socket.emit('command', { command: currentCommand.trim() });
                }
                currentCommand = '';
                // Do not emit prompt here; server will send it when ready
                break;
            case '\u0003': // Ctrl+C
                term.write('^C\r\n');
                // Emit a signal to terminate the command on the server
                socket.emit('command', { command: 'SIGINT' });
                currentCommand = '';
                // Do not emit prompt here; server will send it when ready
                break;
            case '\u007F': // Backspace (DEL)
                if (currentCommand.length > 0) {
                    // Remove the last character from currentCommand
                    currentCommand = currentCommand.slice(0, -1);
                    // Move the cursor back, erase the character, and move the cursor back again
                    term.write('\b \b');
                }
                break;
            default:
                // Only add printable characters to currentCommand
                if (
                    e >= String.fromCharCode(0x20) &&
                    e <= String.fromCharCode(0x7e)
                ) {
                    currentCommand += e;
                    term.write(e);
                }
                break;
        }
    });
}

/********************************************************************
 * SECTION 5: Strip Code Fences Function
 * ---------------------------------------------------------------
 * Removes markdown code fences from the assembled code.
 ********************************************************************/
function stripCodeFencing(code) {
    // Remove opening code fences (e.g., ```python or ```)
    code = code.replace(/^```[\w]*\n/, '');
    // Remove closing code fences
    code = code.replace(/```$/, '');
    // Trim any leading/trailing whitespace
    return code.trim();
}

/********************************************************************
 * SECTION 6: Update Editor Content
 * ---------------------------------------------------------------
 * Updates the editor content with the processed code.
 ********************************************************************/
function updateEditorContent(fileName, code) {
  fileContents[fileName] = code;
  
  if (fileName === currentFileName) {
      // Disable editor during typing simulation
      editor.setReadOnly(true);
      isTyping = true;
      editor.setValue('');
      // We'll let simulateTypingInEditor handle the clearing
      simulateTypingInEditor(code)
          .then(() => {
              // Re-enable editor after typing is complete
              editor.setReadOnly(false);
              // Clear the editor and move the cursor to the beginning
              

              isTyping = false;

              // Set editor mode based on file extension
              var extension = fileName.split('.').pop();
              var mode = getEditorMode(extension);
              editor.session.setMode('ace/mode/' + mode);

              // Scroll to bottom after setting content
              editor.gotoLine(editor.session.getLength(), 0, true);

              // Clear terminal and append prompt
              if (term) {
                  term.clear();
                  appendToConsole('Updated content for file: ' + fileName + '\n', 'system');
                  appendToConsole(PROMPT, 'prompt');
              }

              // After code typing is complete, simulate typing the testing commands
              if (testingCommands && testingCommands.length > 0) {
                  return simulateTypingCommands(testingCommands);
              }
              return Promise.resolve();
          })
          .then(() => {
              if (testingCommands && testingCommands.length > 0) {
                  console.log('Finished typing testing commands.');
              }
          })
          .catch((error) => {
              console.error('Error during typing simulation:', error);
              editor.setReadOnly(false);
              isTyping = false;
          });
  }
}

/********************************************************************
 * SECTION 7: Simulate Typing in Editor
 * ---------------------------------------------------------------
 * Simulates typing code into the editor, character by character.
 ********************************************************************/
function simulateTypingInEditor(code) {
  return new Promise((resolve, reject) => {
      typingCounter++;
      console.log(`Typing started. Active typings: ${typingCounter}`);

      let charIndex = 0;
      const typingSpeed = 10;
      
      // Get the editor document
      const doc = editor.getSession().getDocument();
      let currentRow = 0;
      let currentColumn = 0;

      function typeNextChar() {
          if (charIndex < code.length) {
              const char = code[charIndex];
              
              if (char === '\n') {
                  doc.insert({row: currentRow, column: currentColumn}, '\n');
                  currentRow++;
                  currentColumn = 0;
              } else {
                  doc.insert({row: currentRow, column: currentColumn}, char);
                  currentColumn++;
              }
              
              charIndex++;
              setTimeout(typeNextChar, typingSpeed);
          } else {
              typingCounter--;
              console.log(`Typing completed. Active typings: ${typingCounter}`);

              if (typingCounter === 0 && pendingGUIData) {
                  showGUI(pendingGUIData);
                  appendToConsole('GUI is now displayed after typing completion.\n', 'system');
                  pendingGUIData = null;
              }
              resolve();
          }
      }

      // Clear the document
      typeNextChar();
  });
}

/********************************************************************
 * SECTION 8: Simulate Typing Commands in Terminal
 * ---------------------------------------------------------------
 * Simulates typing commands into the terminal and handles execution.
 ********************************************************************/
function simulateTypingCommands(commands) {
    return commands.reduce((promiseChain, currentCommand) => {
        return promiseChain.then(() => {
            return simulateTypingInTerminal(currentCommand);
        });
    }, Promise.resolve());
}

function simulateTypingInTerminal(command) {
    return new Promise((resolve, reject) => {
        // Increment typing counter
        typingCounter++;
        console.log(`Terminal typing started. Active typings: ${typingCounter}`);

        let i = 0;
        const typingSpeed = 50; // Typing speed in milliseconds per character

        function typeNextChar() {
            if (i < command.length) {
                const char = command[i];
                // Insert character into the terminal
                term.write(char);
                i++;
                setTimeout(typeNextChar, typingSpeed);
            } else {
                // After typing the command, simulate pressing Enter
                term.write('\r\n');
                // Emit the command to the server for execution
                socket.emit('command', { command: command, source: 'automation' });

                // Wait for the command execution to complete
                function onMessage(data) {
                    if (data.type === 'prompt') {
                        console.log('Received prompt after command execution:', data);
                        socket.off('message', onMessage); // Remove listener
                        clearTimeout(timeout); // Clear the timeout

                        // Decrement typing counter
                        typingCounter--;
                        console.log(`Terminal typing completed. Active typings: ${typingCounter}`);

                        // Check if GUI needs to be shown
                        if (typingCounter === 0 && pendingGUIData) {
                            showGUI(pendingGUIData);
                            appendToConsole('GUI is now displayed after typing completion.\n', 'system');
                            pendingGUIData = null;
                        }

                        resolve();
                    }
                }

                socket.on('message', onMessage);

                // Set a timeout in case the prompt is not received
                const timeout = setTimeout(() => {
                    socket.off('message', onMessage);
                    typingCounter--;
                    console.log(`Command execution timed out. Active typings: ${typingCounter}`);
                    reject(new Error('Command execution timed out.'));
                }, 30000); // 30 seconds timeout
            }
        }

        // Start typing
        typeNextChar();
    });
}

/********************************************************************
 * SECTION 9: Show GUI Function
 * ---------------------------------------------------------------
 * Displays the GUI image after typing is complete.
 ********************************************************************/
function showGUI(data) {
    const overlay = document.getElementById('gui-window');
    const guiImage = document.getElementById('gui-image');
    const closeOverlayBtn = document.getElementById('close-overlay');

    if (!overlay || !guiImage || !closeOverlayBtn) {
        console.error('Error: GUI overlay elements not found');
        return;
    }

    // If data is provided, set the image source
    if (data && data.data) {
        guiImage.src = 'data:image/png;base64,' + data.data;
    }

    // Show the overlay by removing the 'hidden' class
    overlay.classList.remove('hidden');

    // Add event listener to close the overlay
    closeOverlayBtn.onclick = function () {
        overlay.classList.add('hidden');
        // Optionally clear the image source
        guiImage.src = '';
    };
}

/********************************************************************
 * SECTION 10: Append Text to Console
 * ---------------------------------------------------------------
 * Writes messages to the terminal console, optionally styling
 * them based on the type (e.g., errors in red).
 ********************************************************************/
function appendToConsole(text, type = 'output') {
    if (term) {
        console.log('Appending to console:', text, type); // Debug log
        const sanitizedText = text;

        if (type === 'error') {
            // Write errors in red using ANSI escape codes and ensure they start on a new line
            term.writeln(`\x1b[31m${sanitizedText}\x1b[0m`);
        } else if (type === 'system') {
            // Write system messages in blue
            term.writeln(`\x1b[34m${sanitizedText}\x1b[0m`);
        } else if (type === 'prompt') {
            // Use 'term.write' to keep the prompt on the same line
            term.write(`${sanitizedText}`);
        } else {
            // Write regular output
            term.writeln(`${sanitizedText}`);
        }

        // Scroll to the bottom of the terminal
        term.scrollToBottom();
    } else {
        console.error('Terminal instance not initialized.');
    }
}


/********************************************************************
 * SECTION 11: Validate File Name
 * ---------------------------------------------------------------
 * Ensures that the provided file name contains only allowed
 * characters.
 ********************************************************************/
function isValidFileName(fileName) {
    // Allow only alphanumeric characters, underscores, hyphens, and dots
    var regex = /^[a-zA-Z0-9_\-\.]+$/;
    return regex.test(fileName);
}

/********************************************************************
 * SECTION 12: Save File to Server
 * ---------------------------------------------------------------
 * Sends a POST request to save the file content on the server.
 ********************************************************************/
function saveFile(fileName, content, source = 'user', prompt = null) {
    console.log(`Saving file '${fileName}' with source '${source}'.`);
    console.log(`Content to save:\n${content}`);

    const data = {
        content: content,
        source: source,
    };

    // Include the prompt only if the source is 'milo' and prompt is provided
    if (source === 'milo' && prompt) {
        data.prompt = prompt;
        console.log(`Including prompt for 'milo': ${prompt}`);
    }

    return fetch(`/save_file/${fileName}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(errData => {
                throw new Error(errData.error || 'Failed to save the file.');
            });
        }
        return response.json();
    });
}

/********************************************************************
 * SECTION 13: Get Editor Content for a Specific File
 * ---------------------------------------------------------------
 * Retrieves the content from the Ace Editor for a given file.
 ********************************************************************/
function getEditorContentForFile(fileName) {
    if (fileName === currentFileName) {
        return editor.getValue();
    } else {
        return fileContents[fileName] || '';
    }
}

/********************************************************************
 * SECTION 14: Show Loading Spinner
 * ---------------------------------------------------------------
 * Displays the loading spinner to indicate ongoing operations.
 ********************************************************************/
function showLoading() {
    const spinner = document.getElementById('global-loading-spinner');
    if (spinner) {
        spinner.classList.remove('hidden');
    } else {
        console.error("Element with id 'global-loading-spinner' not found.");
    }
}

function hideLoading() {
    const spinner = document.getElementById('global-loading-spinner');
    if (spinner) {
        spinner.classList.add('hidden');
    } else {
        console.error("Element with id 'global-loading-spinner' not found.");
    }
}


/********************************************************************
 * SECTION 17: Create New Tab and Corresponding File
 * ---------------------------------------------------------------
 * Creates a new tab in the UI and the corresponding file on the
 * server. If the file already exists, it simply switches to the
 * existing tab.
 ********************************************************************/
function createNewTab(fileName) {
    return new Promise((resolve, reject) => {
        // Check if file already exists
        var existingTab = document.querySelector(
            `.tab[data-file-name="${fileName}"]`
        );
        if (existingTab) {
            console.log(`Tab for file '${fileName}' already exists. Switching to it.`);
            switchToTab(fileName);
            resolve();
            return;
        }

        // Create the tab element
        var tab = document.createElement('div');
        tab.classList.add('tab');
        tab.setAttribute('data-file-name', fileName);
        tab.innerText = fileName;

        // Create the close button for the tab
        var closeBtn = document.createElement('button');
        closeBtn.classList.add('close-btn');
        closeBtn.innerText = '×';
        closeBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            closeTab(fileName);
        });
        tab.appendChild(closeBtn);

        // Add click event to switch tabs
        tab.addEventListener('click', function () {
            console.log(`Switching to tab: '${fileName}'`);
            switchToTab(fileName);
        });

        // Append the new tab to the tabs container
        tabsDiv.appendChild(tab);
        console.log(`New tab created for file: '${fileName}'`);
        switchToTab(fileName);

        // Create the file on the server
        createFile(fileName)
            .then((data) => {
                if (data && (data.status === 'success' || data.status === 'exists')) {
                    console.log(
                        `File '${fileName}' created successfully on the server.`
                    );

                    // Initialize file content based on creation status
                    if (data.status === 'success') {
                        fileContents[fileName] = ''; // Newly created file starts empty
                    }

                    // Fetch the file content from the server
                    return fetch(`/get_file/${fileName}`);
                } else {
                    console.log(`File '${fileName}' may already exist on the server.`);
                    resolve();
                }
            })
            .then((response) => {
                if (response && response.ok) {
                    return response.json();
                }
            })
            .then((fileData) => {
                if (fileData && fileData.content !== undefined) {
                    // If the file already existed, load its content
                    if (fileData.content) {
                        fileContents[fileName] = fileData.content;
                    }

                    // If this is the active tab, display its content
                    if (fileName === currentFileName) {
                         // -1 moves cursor to start

                        // Set editor mode based on file extension
                        var extension = fileName.split('.').pop();
                        var mode = getEditorMode(extension);
                        editor.session.setMode('ace/mode/' + mode);

                        // Scroll to bottom after setting content
                        

                        // Clear terminal and append prompt
                        if (term) {
                            term.clear();
                            appendToConsole('Switched to file: ' + fileName + '\n', 'system');
                            appendToConsole(PROMPT, 'prompt');
                        }
                    }
                    console.log(`Content loaded for file '${fileName}'.`);
                } else {
                    appendToConsole(
                        `Error: Unable to load content for file '${fileName}'.\n`,
                        'error'
                    );
                }
                resolve();
            })
            .catch((error) => {
                appendToConsole(
                    `Error: Unable to fetch content for file '${fileName}'. ${error.message}\n`,
                    'error'
                );
                reject(error);
            });
    });
}

function getEditorMode(extension) {
    var modes = {
        py: 'python',
        cpp: 'c_cpp',
        c: 'c_cpp',
        html: 'html',
        js: 'javascript',
        // Add other extensions as needed
    };
    return modes[extension] || 'text';
}

/********************************************************************
 * SECTION 18: Switch to a Specific Tab
 * ---------------------------------------------------------------
 * Changes the active tab in the UI and loads the corresponding file
 * content into the Ace Editor.
 ********************************************************************/
function switchToTab(fileName) {
    var tabs = document.querySelectorAll('.tab');
    tabs.forEach(function (tab) {
        if (tab.getAttribute('data-file-name') === fileName) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });

    currentFileName = fileName;

    // Load the content from fileContents or fetch from server
    if (fileContents[fileName] !== undefined) {
        editor.setValue(fileContents[fileName], -1); // -1 moves cursor to start
    } else {
        // Fetch the file content from the server
        getFileContent(fileName)
            .then((data) => {
                if (data.content !== undefined) {
                    
                } else {
                    appendToConsole('Error: Unable to load file content.\r\n', 'error');
                }
            })
            .catch((error) => {
                appendToConsole('Error: ' + error.message + '\n', 'error');
            });
    }

    // Set editor mode based on file extension
    var extension = fileName.split('.').pop();
    var mode = getEditorMode(extension);
    editor.session.setMode('ace/mode/' + mode);

    // Clear terminal when switching files
    if (term) {
        term.clear();
        appendToConsole('Switched to file: ' + fileName + '\r\n', 'system');
        appendToConsole(PROMPT, 'prompt');
    }
}

/********************************************************************
 * SECTION 19: Get File Content from Server
 * ---------------------------------------------------------------
 * Sends a GET request to retrieve the content of a specified file
 * from the server.
 ********************************************************************/
function getFileContent(fileName) {
    return fetch(`/get_file/${fileName}`).then((response) => {
        if (!response.ok) {
            return response.json().then((errData) => {
                throw new Error(
                    errData.error ||
                    'Unknown error occurred while fetching file content.'
                );
            });
        }
        return response.json();
    });
}

/********************************************************************
 * SECTION 20: Create File on Server
 * ---------------------------------------------------------------
 * Sends a POST request to create a new file on the server.
 ********************************************************************/
function createFile(fileName) {
    console.log(`Creating file: '${fileName}'`);

    // Validate file name before sending
    if (!isValidFileName(fileName)) {
        alert(
            'Invalid file name. Only letters, numbers, underscores, hyphens, and dots are allowed.'
        );
        return Promise.reject(new Error('Invalid file name format.'));
    }

    return fetch(`/create_file`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ file_name: fileName }),
    })
    .then((response) => {
        if (!response.ok) {
            return response.json().then((errData) => {
                // If the error is 'File already exists.', proceed anyway
                if (errData.error === 'File already exists.') {
                    console.warn(
                        `File '${fileName}' already exists on the server. Proceeding without creating it.`
                    );
                    return { status: 'exists' }; // Indicate that the file exists
                } else {
                    throw new Error(errData.error || 'Unknown error occurred.');
                }
            });
        }
        return response.json();
    })
    .then((data) => {
        console.log(`File creation response: ${JSON.stringify(data)}`);
        return data;
    })
    .catch((error) => {
        console.error(`File creation failed: ${error.message}`);
        throw error;
    });
}

/********************************************************************
 * SECTION 21: Close Tab and Delete File
 * ---------------------------------------------------------------
 * Removes a tab from the UI and deletes the corresponding file
 * from the server. If the closed tab was active, switches to
 * another available tab or clears the editor.
 ********************************************************************/
function closeTab(fileName) {
    var tab = document.querySelector(`.tab[data-file-name="${fileName}"]`);
    if (tab) {
        tab.remove();

        // Delete file on the server with enhanced error handling
        fetch(`/delete_file/${fileName}`, {
            method: 'POST',
        })
        .then((response) => response.json())
        .then((data) => {
            if (data.status !== 'success') {
                appendToConsole('Error: Unable to delete file.\r\n', 'error');
            } else {
                console.log(
                    `File '${fileName}' deleted successfully from the server.`
                );
                delete fileContents[fileName]; // Remove from local storage
            }
        })
        .catch((error) => {
            appendToConsole('Error: ' + error.message + '\r\n', 'error');
        });

        // If the closed tab was active, switch to another tab
        if (currentFileName === fileName) {
            var remainingTabs = document.querySelectorAll(`.tab[data-file-name]`);
            if (remainingTabs.length > 0) {
                var firstTab = remainingTabs[0];
                var newFileName = firstTab.getAttribute('data-file-name');
                switchToTab(newFileName);
            } else {
                
                currentFileName = '';
                if (term) {
                    term.clear();
                    appendToConsole('No active session.\r\n', 'system');
                    // Optionally hide the terminal
                    document.getElementById('terminal-container').style.display = 'none';
                }
            }
        }
    }
}

/********************************************************************
 * SECTION 22: Toggle Panel Visibility
 * ---------------------------------------------------------------
 * Toggles the visibility of specified panels (lint, version history,
 * collaborators).
 ********************************************************************/
function togglePanel(panelId) {
    var panel = document.getElementById(panelId);
    if (panel) {
        if (panel.style.display === 'none' || panel.style.display === '') {
            panel.style.display = 'block';
        } else {
            panel.style.display = 'none';
        }
    } else {
        console.warn(`Panel with id '${panelId}' not found.`);
    }
}

/********************************************************************
 * SECTION 23: Initialize Drag-and-Drop for Panels
 * ---------------------------------------------------------------
 * Sets up Interact.js to allow panels to be rearranged via drag-and-drop.
 ********************************************************************/
function initializeDragAndDrop() {
    interact('.panel-header').draggable({
        // Enable inertial throwing
        inertia: true,
        // Keep the element within the area of the parent
        modifiers: [
            interact.modifiers.restrictRect({
                restriction: 'parent',
                endOnly: true,
            }),
        ],
        // Enable autoScroll
        autoScroll: true,
        // Call this function on every dragmove event
        onmove: dragMoveListener,
        // Call this function on end event
        onend: function (event) {
            // You can add any cleanup or additional actions here
            console.log('Drag ended');
        },
    });

    function dragMoveListener(event) {
        var target = event.target.parentElement; // The panel being dragged
        // Translate the panel by the delta
        var dataX = (parseFloat(target.getAttribute('data-x')) || 0) + event.dx;
        var dataY = (parseFloat(target.getAttribute('data-y')) || 0) + event.dy;

        // Apply translation
        target.style.transform = `translate(${dataX}px, ${dataY}px)`;

        // Update the position attributes
        target.setAttribute('data-x', dataX);
        target.setAttribute('data-y', dataY);
    }

    // Enable dropping on the panels container
    interact('#panels-container').dropzone({
        // Only accept elements matching this CSS selector
        accept: '.panel',
        // Require a 75% element overlap for a drop to be possible
        overlap: 0.75,

        // Listen for drop related events:
        ondragenter: function (event) {
            var draggableElement = event.relatedTarget;
            var dropzoneElement = event.target;

            // Add active dropzone feedback
            dropzoneElement.classList.add('drop-active');
            draggableElement.classList.add('can-drop');
        },
        ondragleave: function (event) {
            // Remove the drop feedback style
            event.target.classList.remove('drop-active');
            event.relatedTarget.classList.remove('can-drop');
        },
        ondrop: function (event) {
            // Swap the positions of the panels
            var draggableElement = event.relatedTarget;
            var dropzoneElement = event.target;

            // Get the dragged panel and the drop target panel
            var draggedPanel = draggableElement;
            var targetPanel = dropzoneElement.querySelector('.panel');

            if (draggedPanel && targetPanel && draggedPanel !== targetPanel) {
                // Swap the panels in the DOM
                var parent = draggedPanel.parentNode;
                var sibling =
                    targetPanel.nextSibling === draggedPanel
                        ? targetPanel
                        : targetPanel.nextSibling;
                parent.insertBefore(draggedPanel, sibling);
            }

            // Remove drop feedback styles
            dropzoneElement.classList.remove('drop-active');
            draggableElement.classList.remove('can-drop');
        },
        ondropdeactivate: function (event) {
            event.target.classList.remove('drop-active');
            event.target.classList.remove('drop-target');
        },
    });
}

/********************************************************************
 * SECTION 24: Display HTML Output
 * ---------------------------------------------------------------
 * Displays HTML content in the output container.
 ********************************************************************/
function displayHtmlOutput(fileName) {
    // Fetch the file content from the server
    getFileContent(fileName)
        .then((data) => {
            if (data.content !== undefined) {
                var outputContainer = document.getElementById('output-container');
                if (!outputContainer) {
                    console.error('Error: output-container element not found');
                    return;
                }

                // Clear previous content
                outputContainer.innerHTML = '';

                // Create an iframe to display the HTML content securely
                var iframe = document.createElement('iframe');
                iframe.sandbox = 'allow-scripts'; // Adjust sandbox attributes as needed
                iframe.style.width = '100%';
                iframe.style.height = '100%';
                iframe.style.border = 'none';
                iframe.style.margin = '0';
                iframe.style.padding = '0';
                iframe.style.background = '#FFFFFF';

                // Write the HTML content into the iframe
                iframe.srcdoc = data.content;

                // Append the iframe to the output container
                outputContainer.appendChild(iframe);

                appendToConsole(
                    'Displayed HTML content of ' + fileName + '\n',
                    'system'
                );
            } else {
                appendToConsole('Error: Unable to load file content.\r\n', 'error');
            }
        })
        .catch((error) => {
            appendToConsole('Error: ' + error.message + '\n', 'error');
        });
}

/********************************************************************
 * SECTION X: Editor Loading Overlay Control Functions
 * ---------------------------------------------------------------
 * Functions to show and hide the editor loading overlay (spinner).
 ********************************************************************/
function showEditorLoadingOverlay() {
    const overlay = document.getElementById('editor-loading-overlay');
    if (overlay) {
        overlay.classList.remove('hidden');
    }
}

function hideEditorLoadingOverlay() {
    const overlay = document.getElementById('editor-loading-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
    }
}

/********************************************************************
 * SECTION 25: Download Executable Functionality
 * ---------------------------------------------------------------
 * Allows users to package their code into an executable and download
 * it to their computer.
 ********************************************************************/
document.addEventListener('DOMContentLoaded', function () {
    // Initialize Download Executable Button
    const downloadExecutableButton = document.getElementById('downloadExecutableButton');

    if (downloadExecutableButton) {
        downloadExecutableButton.addEventListener('click', function () {
            // Disable the button to prevent multiple clicks
            downloadExecutableButton.disabled = true;

            // Show loading spinner
            showLoading();

            // Prepare data to send to the backend
            const data = {
                file_name: currentFileName,
                code: editor.getValue(),
                language: getLanguageFromFileName(currentFileName)
            };

            // Validate language before proceeding
            if (data.language === 'unknown') {
                appendToConsole('Error: Unsupported language for packaging.\n', 'error');
                hideLoading();
                downloadExecutableButton.disabled = false;
                return;
            }

            // Send POST request to backend to package the executable
            fetch('/package_executable', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data),
            })
            .then(response => {
                if (!response.ok) {
                    // Attempt to extract error message from response
                    return response.json().then(errData => {
                        const errorMessage = errData.error || 'Failed to package the executable.';
                        throw new Error(errorMessage);
                    });
                }
                // Extract the Content-Disposition header
                const disposition = response.headers.get('Content-Disposition');
                return response.blob().then(blob => ({ blob, disposition }));
            })
            .then(({ blob, disposition }) => {
                // Create a URL for the blob
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;

                // Extract filename from Content-Disposition or use default
                let filename = 'executable.zip'; // Default filename
                if (disposition && disposition.indexOf('attachment') !== -1) {
                    const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
                    const matches = filenameRegex.exec(disposition);
                    if (matches != null && matches[1]) { 
                        filename = matches[1].replace(/['"]/g, '');
                    }
                }
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);

                appendToConsole(`Executable downloaded successfully as ${filename}.\n`, 'system');
            })
            .catch(error => {
                appendToConsole(`Error: ${error.message}\n`, 'error');
            })
            .finally(() => {
                // Hide loading spinner and re-enable the button
                hideLoading();
                downloadExecutableButton.disabled = false;
            });
        });
    } else {
        console.warn("Element with id 'downloadExecutableButton' not found.");
    }
});
function simulateTypingCommands(commands) {
  return commands.reduce((promiseChain, currentCommand) => {
      return promiseChain.then(() => {
          return simulateTypingInTerminal(currentCommand);
      });
  }, Promise.resolve());
  
}

/********************************************************************
 * SECTION X: Helper Function to Get Language from File Name
 * ---------------------------------------------------------------
 * Determines the programming language based on the file extension.
 ********************************************************************/
function getLanguageFromFileName(fileName) {
    const extension = fileName.split('.').pop().toLowerCase();
    const languageMap = {
        'py': 'python',
        'cpp': 'cpp',
        'c': 'c',
        'js': 'javascript',
        'html': 'html',
        // Add more mappings as needed
    };
    return languageMap[extension] || 'unknown';
}
async function typeAndExecute(code, command) {
  try {
      // Simulate typing the code into the editor
      await simulateTypingInEditor(code);
      console.log('Typing simulation complete.');

      // Simulate typing the command into the terminal and execute it
      await simulateTypingInTerminal(command);
      console.log('Command typing and execution complete.');

      // The GUI will be shown after typingCounter reaches zero
  } catch (error) {
      console.error('Error during typing and execution:', error);
      appendToConsole(`Error: ${error.message}\n`, 'error');
  }
}
// Debounced save function
const debouncedSave = debounce(function() {
    const content = editor.getValue();
    fileContents[currentFileName] = content; // Update local content
    saveFile(currentFileName, content)
        .then(() => {
            console.log(`File '${currentFileName}' saved successfully.`);
        })
        .catch((error) => {
            console.error(`Failed to save file '${currentFileName}': ${error.message}`);
            appendToConsole(`Error: Unable to save file '${currentFileName}'. ${error.message}\n`, 'error');
        });
}, 1000); // Wait 1 second after the user stops typing
// Add change listener to editor
editor.getSession().on('change', function(delta) {
    debouncedSave();
});


