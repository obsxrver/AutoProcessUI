"""ComfyUI WebSocket handler with proper binary message support"""

import json
import struct
import io
from PIL import Image
import numpy as np


def parse_comfyui_binary_message(data):
    """Parse ComfyUI binary websocket messages
    
    ComfyUI sends binary messages in a specific format:
    - First 4 bytes: message type (1 = preview image)
    - Next 4 bytes: additional info
    - Rest: actual data (e.g., PNG/JPEG image)
    """
    if len(data) < 8:
        return None, None
    
    # Read message type (first 4 bytes as uint32)
    msg_type = struct.unpack('>I', data[:4])[0]
    
    # Read additional info (next 4 bytes)
    info = struct.unpack('>I', data[4:8])[0]
    
    # Extract payload
    payload = data[8:]
    
    return msg_type, payload


def handle_preview_image(image_data):
    """Convert binary image data to PIL Image"""
    try:
        # Try to load as image
        img = Image.open(io.BytesIO(image_data))
        return img
    except Exception as e:
        # Might be raw pixel data, try other formats
        try:
            # Try as raw RGB data (512x512x3)
            if len(image_data) == 512 * 512 * 3:
                arr = np.frombuffer(image_data, dtype=np.uint8)
                arr = arr.reshape((512, 512, 3))
                img = Image.fromarray(arr, 'RGB')
                return img
            # Try as raw RGBA data (512x512x4)
            elif len(image_data) == 512 * 512 * 4:
                arr = np.frombuffer(image_data, dtype=np.uint8)
                arr = arr.reshape((512, 512, 4))
                img = Image.fromarray(arr, 'RGBA')
                return img
        except:
            pass
    
    return None 