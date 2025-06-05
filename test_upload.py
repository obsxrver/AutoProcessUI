#!/usr/bin/env python
"""Test script to verify image upload and processing functionality"""

import os
import sys
import tempfile
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

def test_upload():
    """Test the upload functionality"""
    print("=== Testing Image Upload ===")
    
    # Import the app
    try:
        from gradio_app import GradioComfyUIApp
        print("✓ Successfully imported GradioComfyUIApp")
    except ImportError as e:
        print(f"✗ Failed to import: {e}")
        return
    
    # Create app instance
    try:
        app = GradioComfyUIApp()
        print("✓ Successfully created app instance")
    except Exception as e:
        print(f"✗ Failed to create app: {e}")
        return
    
    # Create test image
    test_img = create_test_image()
    print(f"✓ Created test image: {test_img}")
    
    # Test file processing
    try:
        # Simulate Gradio file object
        class FakeFile:
            def __init__(self, path):
                self.name = path
        
        fake_files = [FakeFile(test_img)]
        
        # Test process_images
        results = app.process_images(
            fake_files, 
            "test positive prompt",
            "test negative prompt"
        )
        
        print("✓ process_images completed")
        print(f"  Results: {len(results[0])} images")
        print(f"  Status: {results[1]}")
        
    except Exception as e:
        print(f"✗ Error in process_images: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        if os.path.exists(test_img):
            os.remove(test_img)
            print("✓ Cleaned up test image")

if __name__ == "__main__":
    test_upload() 