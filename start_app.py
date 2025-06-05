#!/usr/bin/env python
"""Startup wrapper for BatchProcessUI with support for both Gradio and Flask interfaces"""

import os
import sys
import time
import argparse

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
    
    # Check Flask imports
    try:
        import flask
        print(f"✓ Flask version: {flask.__version__}")
    except ImportError:
        print("✗ Flask not installed")
        return False
    
    try:
        import flask_socketio
        print(f"✓ Flask-SocketIO version: {flask_socketio.__version__}")
    except ImportError:
        print("✗ Flask-SocketIO not installed")
        return False
    
    # Check Gradio imports
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
        if torch.cuda.is_available():
            print(f"  CUDA device count: {torch.cuda.device_count()}")
    except ImportError:
        print("⚠ PyTorch not installed (will use CPU mode)")
    
    return True

def launch_flask_app():
    """Launch the Flask application"""
    print("\n✓ Environment check passed. Starting Flask app...\n")
    
    try:
        from app import app, socketio
        
        # Get port from environment or default
        port = int(os.environ.get("FLASK_PORT", "5000"))
        
        print(f"Starting Flask app on port {port}...")
        print(f"Access the interface at: http://localhost:{port}")
        
        # Launch with SocketIO support
        socketio.run(
            app, 
            host='0.0.0.0', 
            port=port, 
            debug=False,
            use_reloader=False
        )
        
    except Exception as e:
        print(f"\n✗ Failed to start Flask app: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def launch_gradio_app():
    """Launch the Gradio application"""
    print("\n✓ Environment check passed. Starting Gradio app...\n")
    
    try:
        from gradio_app import create_interface
        
        # Create and launch interface
        interface = create_interface()
        
        # Enable queuing for progress tracking
        interface.queue()
        
        # Launch with appropriate settings
        # Use port from environment or default to 7860
        port = int(os.environ.get("GRADIO_PORT", "7860"))
        
        print(f"Starting Gradio app on port {port}...")
        print(f"Access the interface at: http://localhost:{port}")
        
        interface.launch(
            server_name="0.0.0.0",
            server_port=port,
            share=False,
            inbrowser=False,
            quiet=False,  # Show startup messages
            show_error=True  # Show errors in console
        )
        
    except Exception as e:
        print(f"\n✗ Failed to start Gradio app: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def main():
    """Main startup function"""
    parser = argparse.ArgumentParser(description="ComfyUI Batch Processor Startup")
    parser.add_argument(
        '--interface', '-i', 
        choices=['flask', 'gradio'], 
        default='flask',
        help='Choose interface type (default: flask)'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        help='Port to run on (overrides environment variables)'
    )
    parser.add_argument(
        '--skip-check',
        action='store_true',
        help='Skip environment checks'
    )
    
    args = parser.parse_args()
    
    print("ComfyUI Batch Processor Startup")
    print(f"Interface: {args.interface.title()}")
    
    # Set port if specified
    if args.port:
        if args.interface == 'flask':
            os.environ['FLASK_PORT'] = str(args.port)
        else:
            os.environ['GRADIO_PORT'] = str(args.port)
        print(f"Port: {args.port}")
    
    print("=" * 50)
    
    # Check environment unless skipped
    if not args.skip_check:
        if not check_environment():
            print("\n✗ Environment check failed. Please check the errors above.")
            print("\nTry installing missing dependencies:")
            print("pip install -r requirements.txt")
            sys.exit(1)
    
    # Launch the appropriate interface
    if args.interface == 'flask':
        launch_flask_app()
    else:
        launch_gradio_app()

if __name__ == "__main__":
    main() 