#!/usr/bin/env python
"""Test script to verify Flask application setup and functionality"""

import os
import sys
import time
import requests
import tempfile
from pathlib import Path
from PIL import Image
import numpy as np

def create_test_image():
    """Create a simple test image"""
    # Create a 512x512 RGB image with random colors
    img_array = np.random.randint(0, 255, (512, 512, 3), dtype=np.uint8)
    img = Image.fromarray(img_array, 'RGB')
    
    # Save to temp file
    temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    img.save(temp_file.name)
    temp_file.close()
    
    return temp_file.name

def test_flask_app():
    """Test the Flask application"""
    print("=== Testing Flask Application ===")
    
    # Check imports
    try:
        from app import app, batch_app
        print("✓ Successfully imported Flask app")
    except ImportError as e:
        print(f"✗ Failed to import Flask app: {e}")
        return False
    
    # Test app initialization
    try:
        cuda_devices = batch_app.detect_cuda_devices()
        print(f"✓ CUDA devices detected: {cuda_devices}")
    except Exception as e:
        print(f"✗ CUDA detection failed: {e}")
        print("  This is expected if PyTorch is not installed")
    
    # Test file upload queue
    try:
        # Create test image
        test_img = create_test_image()
        print(f"✓ Created test image: {test_img}")
        
        # Test upload queue functionality (without actual file upload)
        initial_queue = batch_app.get_upload_queue_images()
        print(f"✓ Initial upload queue: {len(initial_queue)} items")
        
        # Test status data
        status_data = batch_app.get_status_data()
        print(f"✓ Status data: {len(status_data)} items")
        
        # Test results
        results = batch_app.get_all_results()
        print(f"✓ Results: {len(results)} items")
        
        # Cleanup
        os.remove(test_img)
        print("✓ Cleaned up test image")
        
    except Exception as e:
        print(f"✗ File operations test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test Flask routes (if app is running)
    try:
        with app.test_client() as client:
            # Test main page
            response = client.get('/')
            if response.status_code == 200:
                print("✓ Main page loads successfully")
            else:
                print(f"✗ Main page failed: {response.status_code}")
            
            # Test status endpoint
            response = client.get('/status')
            if response.status_code == 200:
                print("✓ Status endpoint works")
            else:
                print(f"✗ Status endpoint failed: {response.status_code}")
        
    except Exception as e:
        print(f"✗ Route testing failed: {e}")
        return False
    
    print("\n✓ All Flask tests passed!")
    return True

def test_gradio_fallback():
    """Test Gradio app as fallback"""
    print("\n=== Testing Gradio Fallback ===")
    
    try:
        from gradio_app import GradioComfyUIApp
        
        # Test app creation (but don't initialize orchestrator)
        print("✓ Gradio app imports successfully")
        return True
        
    except ImportError as e:
        print(f"✗ Gradio app import failed: {e}")
        return False
    except Exception as e:
        print(f"✗ Gradio app test failed: {e}")
        return False

def test_comfyui_connection():
    """Test ComfyUI connection without starting servers"""
    print("\n=== Testing ComfyUI Configuration ===")
    
    # Check ComfyUI path
    comfyui_path = os.environ.get("COMFYUI_PATH")
    if not comfyui_path:
        workspace = os.environ.get("WORKSPACE", "/workspace")
        comfyui_path = os.path.join(workspace, "ComfyUI")
    
    if os.path.exists(comfyui_path):
        print(f"✓ ComfyUI path exists: {comfyui_path}")
        
        # Check for main.py
        main_py = os.path.join(comfyui_path, "main.py")
        if os.path.exists(main_py):
            print("✓ ComfyUI main.py found")
        else:
            print("✗ ComfyUI main.py not found")
            return False
            
        # Check input directory
        input_dir = os.path.join(comfyui_path, "input")
        if os.path.exists(input_dir):
            print("✓ ComfyUI input directory exists")
        else:
            print("✗ ComfyUI input directory not found")
            
        return True
    else:
        print(f"✗ ComfyUI path not found: {comfyui_path}")
        return False

def main():
    """Run all tests"""
    print("ComfyUI Batch Processor - Flask Test Suite")
    print("=" * 50)
    
    all_passed = True
    
    # Test Flask app
    if not test_flask_app():
        all_passed = False
    
    # Test Gradio fallback
    if not test_gradio_fallback():
        all_passed = False
    
    # Test ComfyUI configuration
    if not test_comfyui_connection():
        all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("✓ All tests passed! Flask app is ready to use.")
        print("\nTo start the Flask app:")
        print("  python app.py")
        print("  # or")
        print("  python start_app.py --interface flask")
    else:
        print("✗ Some tests failed. Please check the errors above.")
        print("\nCommon fixes:")
        print("  pip install -r requirements.txt")
        print("  export COMFYUI_PATH=/path/to/ComfyUI")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)