#!/usr/bin/env python
"""Startup wrapper for BatchProcessUI with error handling"""

import os
import sys
import time

def check_environment():
    """Check and report on environment setup"""
    print("=== BatchProcessUI Startup Check ===")
    
    # Check ComfyUI path
    comfyui_path = os.environ.get("COMFYUI_PATH")
    if not comfyui_path:
        # Try to detect ComfyUI path
        workspace = os.environ.get("WORKSPACE", "/workspace")
        comfyui_path = os.path.join(workspace, "ComfyUI")
        if os.path.exists(comfyui_path):
            os.environ["COMFYUI_PATH"] = comfyui_path
            print(f"✓ Set COMFYUI_PATH to: {comfyui_path}")
        else:
            print(f"✗ ComfyUI not found at: {comfyui_path}")
            return False
    else:
        print(f"✓ COMFYUI_PATH set to: {comfyui_path}")
    
    # Check for workflow.json
    if not os.path.exists("workflow.json"):
        print("✗ workflow.json not found in current directory")
        return False
    print("✓ workflow.json found")
    
    # Check imports
    try:
        import gradio
        print(f"✓ Gradio version: {gradio.__version__}")
    except ImportError:
        print("✗ Gradio not installed")
        return False
    
    try:
        import aiohttp
        print(f"✓ aiohttp version: {aiohttp.__version__}")
    except ImportError:
        print("✗ aiohttp not installed")
        return False
    
    try:
        import pandas
        print(f"✓ pandas version: {pandas.__version__}")
    except ImportError:
        print("✗ pandas not installed")
        return False
    
    # Optional: check PyTorch
    try:
        import torch
        print(f"✓ PyTorch version: {torch.__version__}")
        print(f"  CUDA available: {torch.cuda.is_available()}")
    except ImportError:
        print("⚠ PyTorch not installed (will use CPU mode)")
    
    return True

def main():
    """Main startup function"""
    print("Starting BatchProcessUI...")
    
    # Check environment
    if not check_environment():
        print("\n✗ Environment check failed. Please check the errors above.")
        sys.exit(1)
    
    print("\n✓ Environment check passed. Starting Gradio app...\n")
    
    # Import and run the app
    try:
        from gradio_app import create_interface
        
        # Create and launch interface
        interface = create_interface()
        
        # Enable queuing for progress tracking
        interface.queue()
        
        # Launch with appropriate settings for vast.ai
        # Use port from environment or default to 7860
        port = int(os.environ.get("GRADIO_PORT", "7860"))
        
        interface.launch(
            server_name="0.0.0.0",
            server_port=port,
            share=False,
            inbrowser=False,
            quiet=False,  # Show startup messages
            show_error=True  # Show errors in console
        )
        
    except Exception as e:
        print(f"\n✗ Failed to start app: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main() 