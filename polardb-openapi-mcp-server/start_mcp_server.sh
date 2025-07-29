#!/bin/bash

# Check if path parameter is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <path_to_polardb_server>"
    echo "Example: $0 /Users/panfeng/git/polardb_mcp_server/polardb-openapi-mcp-server"
    exit 1
fi

# Get the path from the first argument
SERVER_PATH="$1"

# Check if the directory exists
if [ ! -d "$SERVER_PATH" ]; then
    echo "Error: Directory '$SERVER_PATH' does not exist"
    exit 1
fi

cd "$SERVER_PATH"

# Create virtual environment if it doesn't exist
if [ ! -d "bin" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .
fi

# Activate virtual environment
echo "Activating virtual environment..."
source ./bin/activate

# Verify pip is available and upgrade it
echo "Upgrading pip..."
python3 -m pip install --upgrade pip

# Install requirements
echo "Installing requirements..."
if [ -f "requirements.txt" ]; then
    python3 -m pip install -r requirements.txt --upgrade
else
    echo "Warning: requirements.txt not found, installing pytz manually..."
    python3 -m pip install pytz
fi

# Verify pytz installation
echo "Verifying pytz installation..."
python3 -c "import pytz; print('pytz installed successfully')" || {
    echo "Installing pytz..."
    python3 -m pip install pytz
}

# Run the server
python3 server.py
