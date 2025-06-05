#!/usr/bin/env python
"""Test script to verify environment setup for BatchProcessUI"""

import sys
import os

print("=== BatchProcessUI Environment Test ===")
print(f"Python version: {sys.version}")
print(f"Working directory: {os.getcwd()}")

# Test imports
try:
    import gradio as gr
    print(f"✓ Gradio version: {gr.__version__}")
except ImportError as e:
    print(f"✗ Gradio import failed: {e}")

try:
    import aiohttp
    print(f"✓ aiohttp version: {aiohttp.__version__}")
except ImportError as e:
    print(f"✗ aiohttp import failed: {e}")

try:
    import torch
    print(f"✓ PyTorch version: {torch.__version__}")
    print(f"  CUDA available: {torch.cuda.is_available()}")
    print(f"  CUDA device count: {torch.cuda.device_count()}")
except ImportError as e:
    print(f"✗ PyTorch import failed: {e}")

try:
    import pandas as pd
    print(f"✓ Pandas version: {pd.__version__}")
except ImportError as e:
    print(f"✗ Pandas import failed: {e}")

# Test ComfyUI path
comfyui_path = os.environ.get("COMFYUI_PATH", "${WORKSPACE}/ComfyUI")
comfyui_path = os.path.expandvars(comfyui_path)
if os.path.exists(comfyui_path):
    print(f"✓ ComfyUI path exists: {comfyui_path}")
else:
    print(f"✗ ComfyUI path not found: {comfyui_path}")

# Test workflow file
if os.path.exists("workflow.json"):
    print("✓ workflow.json found")
else:
    print("✗ workflow.json not found")

# Test network connectivity
try:
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    result = sock.connect_ex(('127.0.0.1', 7860))
    sock.close()
    if result == 0:
        print("✗ Port 7860 is already in use")
    else:
        print("✓ Port 7860 is available")
except Exception as e:
    print(f"✗ Port check failed: {e}")

print("\n=== Test Complete ===") 