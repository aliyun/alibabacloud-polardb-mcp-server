#!/bin/bash

# PolarDB MCP Server - Web Client Startup Script
echo "🚀 Starting PolarDB MCP Server Web Client..."

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment not found. Please run setup first:"
    echo "   uv venv"
    echo "   source .venv/bin/activate"
    echo "   uv pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment and start web client
echo "⚡ Activating virtual environment..."
source .venv/bin/activate

# Ensure Flask is installed
echo "📦 Checking Flask installation..."
uv pip install flask>=2.0.0

# Get the absolute path to current directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "📁 Starting web client from: $SCRIPT_DIR"
echo "🌐 Web interface will be available at: http://localhost:4657"
echo "🔧 Press Ctrl+C to stop the server"
echo ""

# Start the web client
python3 fixed_mcp_protocol_web.py "$SCRIPT_DIR"