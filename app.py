#!/usr/bin/env python
"""Flask-based ComfyUI Batch Processor"""

import os
import json
import time
import uuid
import shutil
import zipfile
import asyncio
import threading
from pathlib import Path
from datetime import datetime
from queue import Queue
from typing import List, Dict, Any

from flask import Flask, render_template, request, jsonify, send_file, send_from_directory, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
import pandas as pd
import websocket
import struct
from PIL import Image
import io
import requests

# Import the ComfyUI processing logic
from batchProcess import ComfyUIMultiGPU

# Import ComfyUI websocket handler if available
try:
    from comfyui_websocket import parse_comfyui_binary_message, handle_preview_image
except ImportError:
    # Fallback implementations
    def parse_comfyui_binary_message(data):
        if len(data) < 8:
            return None, None
        msg_type = struct.unpack('>I', data[:4])[0]
        payload = data[8:]
        return msg_type, payload
    
    def handle_preview_image(image_data):
        try:
            return Image.open(io.BytesIO(image_data))
        except:
            return None

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size
app.config['UPLOAD_FOLDER'] = 'temp_inputs'
app.config['OUTPUT_FOLDER'] = 'gradio_outputs'

# Initialize SocketIO for real-time updates
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

class FlaskComfyUIApp:
    def __init__(self):
        self.output_dir = Path(app.config['OUTPUT_FOLDER'])
        self.output_dir.mkdir(exist_ok=True)
        self.temp_input_dir = Path(app.config['UPLOAD_FOLDER'])
        self.temp_input_dir.mkdir(exist_ok=True)
        
        # Load default prompts from workflow.json
        with open("workflow.json", 'r') as f:
            workflow = json.load(f)
        
        self.default_positive = workflow["10"]["inputs"]["text"]
        self.default_negative = workflow["15"]["inputs"]["text"]
        
        # Store processing results
        self.results_cache = {}
        self.processing_status = {}
        
        # Re-processing functionality
        self.reprocess_queue = {}  # Store images marked for re-processing
        
        # Initialize orchestrator (will be created when processing starts)
        self.orchestrator = None
        self.comfyui_processes = []
        
        # Store preview images and websocket connections
        self.preview_images = {}
        self.ws_connections = {}
        self.upload_queue = {}  # Store uploaded images with IDs for deletion
        
        # Final status attributes
        self.final_status = None
        self.final_archive = None
        
        # Stop processing flag
        self.stop_processing = False
        
        # Pre-warm ComfyUI servers on startup
        print("Pre-warming ComfyUI servers...")
        try:
            self.initialize_orchestrator()
            print("ComfyUI servers ready!")
        except Exception as e:
            print(f"Warning: Failed to pre-warm ComfyUI servers: {e}")
            print("Servers will be started on first use.")
    
    def detect_cuda_devices(self):
        """Detect available CUDA devices"""
        try:
            import torch
            cuda_count = torch.cuda.device_count()
            print(f"Detected {cuda_count} CUDA devices")
            return cuda_count if cuda_count > 0 else 1
        except ImportError:
            print("PyTorch not found, assuming 1 GPU")
            return 1
        except Exception as e:
            print(f"Error detecting CUDA devices: {e}, assuming 1 GPU")
            return 1
    
    def initialize_orchestrator(self):
        """Initialize the ComfyUI orchestrator with detected GPUs"""
        if self.orchestrator is None:
            num_gpus = self.detect_cuda_devices()
            
            # Determine ComfyUI path - check common locations
            comfyui_path = os.environ.get("COMFYUI_PATH")
            if not comfyui_path:
                # Check common paths
                possible_paths = [
                    "/workspace/ComfyUI",
                    "C:/ComfyUI",
                    "C:/Users/ComfyUI",
                    os.path.expanduser("~/ComfyUI"),
                    "../ComfyUI",
                    "./ComfyUI"
                ]
                for path in possible_paths:
                    if os.path.exists(path) and os.path.isdir(path):
                        comfyui_path = path
                        break
                else:
                    raise ValueError("ComfyUI path not found. Please set COMFYUI_PATH environment variable.")
            
            print(f"Using ComfyUI path: {comfyui_path}")
            print(f"Initializing with {num_gpus} GPU(s)")
            
            self.orchestrator = ComfyUIMultiGPU(
                workflow_path="workflow.json",
                num_gpus=num_gpus,
                comfyui_path=comfyui_path,
                base_port=8200
            )
            # Start ComfyUI instances
            self.comfyui_processes = self.orchestrator.start_comfyui_instances()
            
            # Wait for servers to initialize
            print("Waiting for ComfyUI servers to initialize...")
            time.sleep(10)
            
            # Verify all servers are running
            all_running = True
            for i, port in enumerate(self.orchestrator.base_ports):
                server_url = f"http://localhost:{port}"
                if not self.orchestrator.check_server(server_url):
                    print(f"Warning: ComfyUI server on port {port} (GPU {i}) is not responding")
                    all_running = False
                else:
                    print(f"✓ ComfyUI server on port {port} (GPU {i}) is ready")
            
            if not all_running:
                print("Warning: Not all ComfyUI servers are running properly")
    
    def monitor_progress_websocket(self, gpu_id, client_id, image_id):
        """Monitor ComfyUI progress via websocket for live previews"""
        ws_url = f"ws://localhost:{self.orchestrator.base_ports[gpu_id]}/ws?clientId={client_id}"
        
        def on_message(ws, message):
            try:
                # Check if message is binary (preview image) or text (JSON)
                if isinstance(message, bytes):
                    # Binary message - parse ComfyUI format
                    msg_type, payload = parse_comfyui_binary_message(message)
                    
                    if msg_type == 1 and payload:  # Type 1 = preview image
                        # Convert to image
                        img = handle_preview_image(payload)
                        if img:
                            # Save temporarily for preview
                            preview_path = self.temp_input_dir / f"preview_{image_id}_{int(time.time()*1000)}.png"
                            img.save(preview_path, 'PNG')
                            self.preview_images[image_id] = str(preview_path)
                            self.processing_status[image_id]['has_preview'] = True
                            
                            # Emit preview update via SocketIO
                            socketio.emit('preview_update', {
                                'image_id': image_id,
                                'preview_path': f"/previews/{preview_path.name}"
                            })
                else:
                    # Text message - parse as JSON
                    data = json.loads(message)
                    
                    # Check for execution updates
                    if data.get('type') == 'executing':
                        node = data.get('data', {}).get('node')
                        if node is not None:
                            self.processing_status[image_id]['current_node'] = node
                            socketio.emit('node_update', {
                                'image_id': image_id,
                                'node': node
                            })
                    
                    elif data.get('type') == 'execution_start':
                        self.processing_status[image_id]['status'] = 'processing'
                        
                    elif data.get('type') == 'progress':
                        progress_data = data.get('data', {})
                        if 'value' in progress_data and 'max' in progress_data:
                            value = progress_data['value']
                            max_val = progress_data['max']
                            if max_val > 0:
                                progress = int((value / max_val) * 100)
                                self.processing_status[image_id]['progress'] = progress
                                socketio.emit('progress_update', {
                                    'image_id': image_id,
                                    'progress': progress
                                })
                    
                    elif data.get('type') == 'executed':
                        # Check for output images
                        output = data.get('data', {}).get('output', {})
                        if 'images' in output:
                            for img in output['images']:
                                if 'filename' in img:
                                    filename = img['filename']
                                    img_type = img.get('type', 'output')
                                    subfolder = img.get('subfolder', '')
                                    
                                    # Build preview URL
                                    if subfolder:
                                        preview_url = f"http://localhost:{self.orchestrator.base_ports[gpu_id]}/view?filename={filename}&subfolder={subfolder}&type={img_type}"
                                    else:
                                        preview_url = f"http://localhost:{self.orchestrator.base_ports[gpu_id]}/view?filename={filename}&type={img_type}"
                                    
                                    # Store as preview
                                    self.preview_images[image_id] = preview_url
                                    
                                    # Emit preview update
                                    socketio.emit('preview_update', {
                                        'image_id': image_id,
                                        'preview_url': preview_url
                                    })
                                    
            except json.JSONDecodeError:
                # Not JSON, might be binary data we couldn't process
                pass
            except Exception as e:
                # Only log if it's not an encoding error (which we expect for binary data)
                if "codec" not in str(e).lower():
                    print(f"Error processing websocket message: {e}")
        
        def on_error(ws, error):
            # Only log non-encoding errors
            if "codec" not in str(error).lower():
                print(f"WebSocket error for GPU {gpu_id}: {error}")
        
        def on_close(ws, close_status_code, close_msg):
            # Use pop() to safely remove items even if they don't exist
            self.ws_connections.pop(image_id, None)
            
            # Clean up preview image if exists
            preview = self.preview_images.pop(image_id, None)
            if preview and isinstance(preview, str) and preview.startswith(str(self.temp_input_dir)):
                try:
                    os.remove(preview)
                except:
                    pass
        
        def on_open(ws):
            print(f"WebSocket connected for GPU {gpu_id}, monitoring {image_id}")
        
        try:
            # Configure websocket to handle binary frames
            ws = websocket.WebSocketApp(ws_url,
                                      on_message=on_message,
                                      on_error=on_error,
                                      on_close=on_close,
                                      on_open=on_open)
            
            self.ws_connections[image_id] = ws
            
            # Run websocket in a separate thread with proper options
            def run_ws():
                ws.run_forever(
                    skip_utf8_validation=True  # Important for binary data
                )
            
            ws_thread = threading.Thread(target=run_ws)
            ws_thread.daemon = True
            ws_thread.start()
            
        except Exception as e:
            print(f"Failed to connect websocket: {e}")
    
    def add_to_upload_queue(self, files):
        """Handle file uploads - single or multiple"""
        if not files:
            return {"status": "error", "message": "No files to upload."}

        # Ensure temp_input_dir exists
        self.temp_input_dir.mkdir(exist_ok=True)
        
        successful_uploads = 0
        failed_uploads = []
        
        # Process each file
        for file in files:
            try:
                if file and file.filename:
                    original_name = secure_filename(file.filename)
                    
                    # Remove existing file with same original name
                    for existing_id, info in list(self.upload_queue.items()):
                        if info['original_name'] == original_name:
                            old_path = info['path']
                            if os.path.exists(old_path):
                                try:
                                    os.remove(old_path)
                                except:
                                    pass
                            del self.upload_queue[existing_id]
                    
                    # Create unique ID and save file
                    upload_id = str(uuid.uuid4())
                    dest_filename = f"{upload_id}_{original_name}"
                    dest_path = self.temp_input_dir / dest_filename
                    
                    file.save(str(dest_path))
                    
                    # Verify save
                    if dest_path.exists() and dest_path.stat().st_size > 0:
                        self.upload_queue[upload_id] = {
                            'path': str(dest_path),
                            'original_name': original_name,
                            'upload_time': time.time()
                        }
                        successful_uploads += 1
                        print(f"✓ Uploaded {original_name}")
                    else:
                        failed_uploads.append(original_name)
                        
            except Exception as e:
                print(f"Error processing file: {e}")
                failed_uploads.append(file.filename if file else "Unknown")
        
        # Status message
        if successful_uploads == len(files):
            status_msg = f"✓ Successfully uploaded {successful_uploads} image(s)"
        elif successful_uploads > 0:
            status_msg = f"⚠️ Uploaded {successful_uploads}/{len(files)} images. Failed: {', '.join(failed_uploads)}"
        else:
            status_msg = f"❌ Failed to upload any images"
        
        return {
            "status": "success" if successful_uploads > 0 else "error",
            "message": status_msg,
            "uploaded_count": successful_uploads,
            "queue_count": len(self.upload_queue)
        }
    
    def get_upload_queue_images(self):
        """Get list of image info for display"""
        return [
            {
                'id': upload_id,
                'path': info['path'],
                'original_name': info['original_name'],
                'upload_time': info['upload_time']
            }
            for upload_id, info in self.upload_queue.items()
        ]
    
    def clear_upload_queue(self):
        """Clear all images from the upload queue"""
        for upload_id, info in list(self.upload_queue.items()):
            temp_path = info['path']
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
        
        self.upload_queue.clear()
        return {"status": "success", "message": "Upload queue cleared"}
    
    def get_all_results(self):
        """Get all processed images for gallery display"""
        all_images = []
        for result in self.results_cache.values():
            for output_path in result.get('output_paths', []):
                all_images.append({
                    'path': output_path,
                    'name': Path(output_path).name,
                    'image_id': result['image_id']
                })
        return all_images
    
    def clear_all_results(self):
        """Clear all results and delete files"""
        # First delete all output files
        if self.output_dir.exists():
            for file_path in self.output_dir.glob("*.png"):
                try:
                    file_path.unlink()
                except Exception as e:
                    print(f"Error deleting {file_path}: {e}")
        
        # Close any open websockets
        # Create a list copy to avoid dictionary modification during iteration
        ws_list = list(self.ws_connections.values())
        for ws in ws_list:
            try:
                ws.close()
            except:
                pass
        self.ws_connections.clear()
        
        # Clear caches
        self.results_cache.clear()
        self.processing_status.clear()
        self.preview_images.clear()
        self.reprocess_queue.clear()
        
        return {"status": "success", "message": "All results cleared"}
    
    def mark_for_reprocessing(self, image_id):
        """Mark an image for re-processing using the original input image"""
        if image_id in self.results_cache:
            result = self.results_cache[image_id]
            
            # Use the original input image for re-processing
            original_input_path = result.get('input_path')
            
            if original_input_path and os.path.exists(original_input_path):
                # Create a copy in the temp inputs directory for re-processing
                temp_filename = f"reprocess_{image_id}_{int(time.time())}.png"
                temp_path = self.temp_input_dir / temp_filename
                shutil.copy2(original_input_path, temp_path)
                
                original_name = Path(original_input_path).name
                
                self.reprocess_queue[image_id] = {
                    'image_id': image_id,
                    'path': str(temp_path),
                    'original_name': f"reprocess_{original_name}",
                    'original_input_path': original_input_path,
                    'original_result': result,
                    'marked_time': time.time()
                }
                return {"status": "success", "message": f"Original image marked for re-processing with different seed"}
            else:
                return {"status": "error", "message": "Original input image not found for re-processing"}
        else:
            return {"status": "error", "message": "Image not found in results"}
    
    def unmark_for_reprocessing(self, image_id):
        """Remove an image from re-processing queue"""
        if image_id in self.reprocess_queue:
            # Clean up temporary file if it was created for re-processing
            reprocess_item = self.reprocess_queue[image_id]
            temp_path = reprocess_item['path']
            if temp_path.startswith(str(self.temp_input_dir)) and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            
            del self.reprocess_queue[image_id]
            return {"status": "success", "message": "Image removed from re-processing queue"}
        else:
            return {"status": "error", "message": "Image not found in re-processing queue"}
    
    def get_reprocess_queue(self):
        """Get list of images marked for re-processing"""
        return [
            {
                'image_id': image_id,
                'original_name': item['original_name'],
                'marked_time': item['marked_time'],
                'path': item['path']
            }
            for image_id, item in self.reprocess_queue.items()
        ]
    
    def clear_reprocess_queue(self):
        """Clear all images from re-processing queue"""
        for image_id, item in list(self.reprocess_queue.items()):
            temp_path = item['path']
            if temp_path.startswith(str(self.temp_input_dir)) and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
        
        self.reprocess_queue.clear()
        return {"status": "success", "message": "Re-processing queue cleared"}
    
    def get_reprocess_count(self):
        """Get count of images in re-processing queue"""
        return len(self.reprocess_queue)
    
    def get_status_data(self):
        """Get processing status data"""
        if not self.processing_status:
            return []
        
        data = []
        for image_id, status in self.processing_status.items():
            status_str = status.get('status', 'Unknown')
            # Add error info if available
            if status_str == 'failed' and 'error' in status:
                status_str = f"failed: {status['error']}"
            
            data.append({
                'image_id': image_id,
                'filename': status.get('filename', 'Unknown'),
                'status': status_str,
                'gpu': status.get('gpu', -1),
                'progress': status.get('progress', 0)
            })
        
        return data
    
    async def process_batch_with_live_updates(self, image_info_list: List[Dict], 
                                            positive_prompt: str, 
                                            negative_prompt: str,
                                            save_unrefined: bool):
        """Process batch of images with live updates via SocketIO"""
        # Reset stop flag at start of processing
        self.stop_processing = False
        
        # Ensure orchestrator is initialized
        if self.orchestrator is None:
            try:
                self.initialize_orchestrator()
            except Exception as e:
                print(f"Fatal: Failed to initialize orchestrator: {e}")
                for image_data in image_info_list:
                    image_id = image_data['image_id']
                    self.processing_status[image_id] = {
                        'filename': image_data['original_name'],
                        'status': 'failed',
                        'gpu': -1,
                        'progress': 0,
                        'input_path': image_data['path'],
                        'error': 'Orchestrator initialization failed'
                    }
                return []
        
        # Import the async processing method from the original class
        import aiohttp
        
        all_results = []
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            
            for i, image_data in enumerate(image_info_list):
                if self.stop_processing:
                    break
                    
                gpu_id = i % self.orchestrator.num_gpus
                image_id = image_data['image_id']
                file_path = image_data['path']
                original_name = image_data['original_name']
                
                self.processing_status[image_id] = {
                    'filename': original_name,
                    'status': 'queued',
                    'gpu': gpu_id,
                    'progress': 0,
                    'input_path': file_path
                }
                
                # Emit status update via SocketIO
                socketio.emit('status_update', {
                    'image_id': image_id,
                    'status': 'queued',
                    'progress': 0,
                    'filename': original_name,
                    'gpu': gpu_id
                })
                
                task = self.process_single_image_with_socketio_updates(
                    session, gpu_id, file_path, original_name, 
                    positive_prompt, negative_prompt, image_id, save_unrefined
                )
                tasks.append(task)
            
            # Process with live updates
            completed_count = 0
            for task_future in asyncio.as_completed(tasks):
                if self.stop_processing:
                    # Cancel remaining tasks
                    for t in tasks:
                        if not t.done():
                            try:
                                t.cancel()
                                await t
                            except asyncio.CancelledError:
                                pass
                            except Exception as e:
                                print(f"Error cancelling task: {e}")
                    
                    # Close websocket connections - create a copy to avoid modification during iteration
                    ws_list = list(self.ws_connections.values())
                    for ws in ws_list:
                        try:
                            ws.close()
                        except:
                            pass
                    self.ws_connections.clear()
                    
                    # Update status for remaining images
                    for image_data in image_info_list[completed_count:]:
                        image_id = image_data['image_id']
                        if image_id in self.processing_status:
                            self.processing_status[image_id]['status'] = 'cancelled'
                            socketio.emit('status_update', {
                                'image_id': image_id,
                                'status': 'cancelled',
                                'progress': 0
                            })
                    
                    socketio.emit('batch_stopped', {
                        'completed': completed_count,
                        'total': len(tasks)
                    })
                    return all_results
                    
                try:
                    result_item = await task_future
                    if result_item:
                        all_results.append(result_item)
                        self.results_cache[result_item['image_id']] = result_item
                        
                        # Emit completion update
                        socketio.emit('processing_complete', {
                            'image_id': result_item['image_id'],
                            'output_paths': result_item['output_paths']
                        })
                    
                    completed_count += 1
                    socketio.emit('batch_progress', {
                        'completed': completed_count,
                        'total': len(tasks)
                    })
                    
                except asyncio.CancelledError:
                    print("Task cancelled due to stop request")
                    continue
                except Exception as e:
                    print(f"Error processing an image task: {e}")
                    completed_count += 1
                    socketio.emit('batch_progress', {
                        'completed': completed_count,
                        'total': len(tasks)
                    })
        
        # Clean up all websocket connections after batch completion
        print(f"Cleaning up {len(self.ws_connections)} websocket connections...")
        ws_list = list(self.ws_connections.values())
        for ws in ws_list:
            try:
                ws.close()
            except Exception as e:
                print(f"Error closing websocket: {e}")
        self.ws_connections.clear()
        
        # Clean up any remaining preview images
        preview_items = list(self.preview_images.items())  # Create a copy of items
        for image_id, preview in preview_items:
            if isinstance(preview, str) and preview.startswith(str(self.temp_input_dir)):
                try:
                    os.remove(preview)
                except:
                    pass
        self.preview_images.clear()  # Clear all at once instead of deleting one by one
        
        return all_results
    
    async def process_single_image_with_socketio_updates(self, session, gpu_id, image_path, 
                                               original_name, positive_prompt, negative_prompt, 
                                               image_id, save_unrefined: bool):
        """Process a single image and provide SocketIO status updates"""
        server_url = f"http://localhost:{self.orchestrator.base_ports[gpu_id]}"
        
        try:
            # Check if server is healthy before processing
            try:
                async with session.get(f"{server_url}/system_stats", timeout=5) as resp:
                    if resp.status != 200:
                        raise Exception(f"Server not healthy: status {resp.status}")
            except Exception as e:
                error_msg = f"ComfyUI server on GPU {gpu_id} is not responding: {str(e)}"
                print(f"Error: {error_msg}")
                
                self.processing_status[image_id]['status'] = 'failed'
                self.processing_status[image_id]['error'] = error_msg
                
                socketio.emit('status_update', {
                    'image_id': image_id,
                    'status': 'failed',
                    'error': error_msg,
                    'gpu': gpu_id,
                    'filename': original_name
                })
                
                return None
            
            # Update status
            self.processing_status[image_id].update({
                'status': 'uploading',
                'progress': 0,
                'filename': original_name  # Ensure filename is always present
            })
            
            socketio.emit('status_update', {
                'image_id': image_id,
                'status': 'uploading',
                'progress': 0,
                'gpu': gpu_id,
                'filename': original_name
            })
            
            # Upload image to server using the API
            upload_result = await self.orchestrator.upload_image_async(
                session, server_url, image_path, original_name
            )
            
            if not upload_result or 'name' not in upload_result:
                error_msg = f"Upload failed for {original_name} via API"
                print(f"Error: {error_msg} - Result: {upload_result}")
                
                self.processing_status[image_id]['status'] = 'failed'
                self.processing_status[image_id]['error'] = error_msg
                
                socketio.emit('status_update', {
                    'image_id': image_id,
                    'status': 'failed',
                    'error': error_msg,
                    'gpu': gpu_id,
                    'filename': original_name
                })
                
                # Clean up websocket connection if it exists (though unlikely at this point)
                ws = self.ws_connections.pop(image_id, None)
                if ws:
                    try:
                        ws.close()
                    except Exception as e:
                        print(f"Error closing websocket for upload failed {image_id}: {e}")
                
                return None
            
            # Modify workflow with custom prompts
            workflow_copy = self.orchestrator.modify_workflow_for_image(upload_result['name'])
            
            # Update prompts in the workflow
            if "10" in workflow_copy:
                workflow_copy["10"]["inputs"]["text"] = positive_prompt
            if "15" in workflow_copy:
                workflow_copy["15"]["inputs"]["text"] = negative_prompt
            
            # Set seeds to -1 for random generation (ComfyUI uses -1 for random)
            # Update seeds in KSampler nodes (node 12 is the main sampler)
            if "12" in workflow_copy and "inputs" in workflow_copy["12"]:
                workflow_copy["12"]["inputs"]["noise_seed"] = -1
            
            # Also update seed in DetailerForEach node (node 46) if present
            if "46" in workflow_copy and "inputs" in workflow_copy["46"]:
                workflow_copy["46"]["inputs"]["seed"] = -1
            
            # Queue prompt
            self.processing_status[image_id]['status'] = 'processing'
            self.processing_status[image_id]['progress'] = 10
            
            socketio.emit('status_update', {
                'image_id': image_id,
                'status': 'processing',
                'progress': 10,
                'gpu': gpu_id,
                'filename': original_name
            })
            
            # Generate client ID for tracking
            client_id = str(uuid.uuid4())
            
            # Start websocket monitoring before queuing
            self.monitor_progress_websocket(gpu_id, client_id, image_id)
            
            payload = {
                "prompt": workflow_copy,
                "client_id": client_id
            }
            
            async with session.post(f"{server_url}/prompt", json=payload) as resp:
                result = await resp.json()
            
            # Log the prompt queue result
            if result and 'prompt_id' in result:
                print(f"Queued prompt {result['prompt_id']} for {original_name}")
            else:
                print(f"Failed to queue prompt for {original_name}: {result}")
            
            if not result or 'prompt_id' not in result:
                error_msg = 'Failed to queue prompt'
                print(f"Error: {error_msg} for {original_name} - Result: {result}")
                
                self.processing_status[image_id]['status'] = 'failed'
                self.processing_status[image_id]['error'] = error_msg
                
                socketio.emit('status_update', {
                    'image_id': image_id,
                    'status': 'failed',
                    'error': error_msg,
                    'gpu': gpu_id,
                    'filename': original_name
                })
                
                # Clean up websocket connection for failed prompt queue
                ws = self.ws_connections.pop(image_id, None)
                if ws:
                    try:
                        ws.close()
                    except Exception as e:
                        print(f"Error closing websocket for failed prompt queue {image_id}: {e}")
                
                return None
            
            prompt_id = result['prompt_id']
            
            # Small delay to ensure prompt is registered before polling
            await asyncio.sleep(0.5)
            
            # Check if the prompt is actually in the queue
            try:
                async with session.get(f"{server_url}/queue") as resp:
                    queue_data = await resp.json()
                    queue_running = queue_data.get('queue_running', [])
                    queue_pending = queue_data.get('queue_pending', [])
                    
                    # Check if our prompt is in any queue
                    in_queue = any(item[1] == prompt_id for item in queue_running) or \
                               any(item[1] == prompt_id for item in queue_pending)
                    
                    if not in_queue:
                        # Check history immediately - it might have completed very quickly
                        history = await self.orchestrator.get_history_async(
                            session, server_url, prompt_id
                        )
                        if not history or prompt_id not in history:
                            print(f"WARNING: Prompt {prompt_id} not found in queue or history!")
            except Exception as e:
                print(f"Error checking queue status: {e}")
            
            # Poll for completion with progress updates (no timeout - let it run until done)
            while True:
                history = await self.orchestrator.get_history_async(
                    session, server_url, prompt_id
                )
                
                if history and prompt_id in history:
                    prompt_history = history[prompt_id]
                    
                    if prompt_history.get('status', {}).get('completed', False):
                        self.processing_status[image_id]['progress'] = 100
                        
                        socketio.emit('status_update', {
                            'image_id': image_id,
                            'status': 'downloading',
                            'progress': 100,
                            'gpu': gpu_id,
                            'filename': original_name
                        })
                        
                        # Get output images
                        outputs = prompt_history.get('outputs', {})
                        output_files = []
                        
                        # Check if we actually have outputs
                        if not outputs:
                            print(f"WARNING: No outputs found for {original_name} even though status is completed!")
                            print(f"Prompt history keys: {list(prompt_history.keys())}")
                        
                        # Download and save outputs with proper naming
                        base_name = Path(image_path).stem
                        
                        def get_unique_filename(base_path):
                            """Get a unique filename by appending numbers if needed"""
                            if not base_path.exists():
                                return base_path
                            
                            counter = 1
                            while True:
                                new_path = base_path.parent / f"{base_path.stem}_{counter}{base_path.suffix}"
                                if not new_path.exists():
                                    return new_path
                                counter += 1
                        
                        # First output (node 20)
                        if "20" in outputs and 'images' in outputs["20"]:
                            for img_info in outputs["20"]['images']:
                                if save_unrefined:  # Only save if user wants unrefined images
                                    filename = img_info['filename']
                                    subfolder = img_info.get('subfolder', '')
                                    
                                    # Download image
                                    if subfolder:
                                        url = f"{server_url}/view?filename={filename}&subfolder={subfolder}&type=output"
                                    else:
                                        url = f"{server_url}/view?filename={filename}&type=output"
                                    
                                    async with session.get(url) as resp:
                                        if resp.status == 200:
                                            content = await resp.read()
                                            
                                            output_path = get_unique_filename(self.output_dir / f"{base_name}_.png")
                                            with open(output_path, 'wb') as f:
                                                f.write(content)
                                            output_files.append(str(output_path))
                        
                        # Second output (node 52 - refined)
                        if "52" in outputs and 'images' in outputs["52"]:
                            for img_info in outputs["52"]['images']:
                                filename = img_info['filename']
                                subfolder = img_info.get('subfolder', '')
                                
                                # Download image
                                if subfolder:
                                    url = f"{server_url}/view?filename={filename}&subfolder={subfolder}&type=output"
                                else:
                                    url = f"{server_url}/view?filename={filename}&type=output"
                                
                                async with session.get(url) as resp:
                                    if resp.status == 200:
                                        content = await resp.read()
                                        
                                        output_path = get_unique_filename(self.output_dir / f"{base_name}_refined.png")
                                        with open(output_path, 'wb') as f:
                                            f.write(content)
                                        output_files.append(str(output_path))
                        
                        self.processing_status[image_id]['status'] = 'completed'
                        
                        socketio.emit('status_update', {
                            'image_id': image_id,
                            'status': 'completed',
                            'progress': 100,
                            'gpu': gpu_id,
                            'filename': original_name
                        })
                        
                        # Clean up websocket connection for this specific image
                        ws = self.ws_connections.pop(image_id, None)
                        if ws:
                            try:
                                ws.close()
                            except Exception as e:
                                print(f"Error closing websocket for image {image_id}: {e}")
                        
                        # Clean up preview image for this specific image
                        preview = self.preview_images.pop(image_id, None)
                        if preview and isinstance(preview, str) and preview.startswith(str(self.temp_input_dir)):
                            try:
                                os.remove(preview)
                            except:
                                pass
                        
                        return {
                            'image_id': image_id,
                            'input_path': image_path,
                            'output_paths': output_files,
                            'status': 'completed'
                        }
                    
                    elif prompt_history.get('status', {}).get('status_str') == 'error':
                        self.processing_status[image_id]['status'] = 'error'
                        socketio.emit('status_update', {
                            'image_id': image_id,
                            'status': 'error',
                            'gpu': gpu_id,
                            'filename': original_name
                        })
                        
                        # Clean up websocket connection for this failed image
                        ws = self.ws_connections.pop(image_id, None)
                        if ws:
                            try:
                                ws.close()
                            except Exception as e:
                                print(f"Error closing websocket for failed image {image_id}: {e}")
                        
                        # Clean up preview image for this failed image
                        preview = self.preview_images.pop(image_id, None)
                        if preview and isinstance(preview, str) and preview.startswith(str(self.temp_input_dir)):
                            try:
                                os.remove(preview)
                            except:
                                pass
                        
                        return None
                    else:
                        # Update progress during processing
                        execution = prompt_history.get('execution', {})
                        if execution:
                            current = execution.get('current', 0)
                            total = execution.get('total', 1)
                            progress = 25 + int((current / total) * 70)
                            self.processing_status[image_id]['progress'] = progress
                            
                            socketio.emit('status_update', {
                                'image_id': image_id,
                                'status': 'processing',
                                'progress': progress,
                                'gpu': gpu_id,
                                'filename': original_name
                            })
                
                await asyncio.sleep(1)
            
        except Exception as e:
            error_msg = str(e)
            print(f"Exception processing {original_name}: {error_msg}")
            import traceback
            traceback.print_exc()
            
            self.processing_status[image_id]['status'] = 'error'
            self.processing_status[image_id]['error'] = error_msg
            
            socketio.emit('status_update', {
                'image_id': image_id,
                'status': 'error',
                'error': error_msg,
                'gpu': gpu_id,
                'filename': original_name
            })
            
            # Clean up websocket connection for this exception case
            ws = self.ws_connections.pop(image_id, None)
            if ws:
                try:
                    ws.close()
                except Exception as cleanup_error:
                    print(f"Error closing websocket for exception case {image_id}: {cleanup_error}")
            
            # Clean up preview image for this exception case
            preview = self.preview_images.pop(image_id, None)
            if preview and isinstance(preview, str) and preview.startswith(str(self.temp_input_dir)):
                try:
                    os.remove(preview)
                except:
                    pass
            
            return None
    
    def create_archive(self, results: List[Dict]) -> str:
        """Create a zip archive of all processed images"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = self.output_dir / f"batch_results_{timestamp}.zip"
        
        with zipfile.ZipFile(archive_path, 'w') as zipf:
            for result in results:
                for output_path in result.get('output_paths', []):
                    if os.path.exists(output_path):
                        arcname = Path(output_path).name
                        zipf.write(output_path, arcname)
        
        return str(archive_path)

# Initialize the app
batch_app = FlaskComfyUIApp()

# Flask Routes
@app.route('/')
def index():
    """Main page"""
    upload_queue = batch_app.get_upload_queue_images()
    results = batch_app.get_all_results()
    status_data = batch_app.get_status_data()
    reprocess_queue = batch_app.get_reprocess_queue()
    
    return render_template('index.html',
                         upload_queue=upload_queue,
                         results=results,
                         status_data=status_data,
                         reprocess_queue=reprocess_queue,
                         default_positive=batch_app.default_positive,
                         default_negative=batch_app.default_negative,
                         cuda_devices=batch_app.detect_cuda_devices())

@app.route('/upload', methods=['POST'])
def upload_files():
    """Handle file uploads"""
    if 'files' not in request.files:
        return jsonify({"status": "error", "message": "No files provided"})
    
    files = request.files.getlist('files')
    result = batch_app.add_to_upload_queue(files)
    
    return jsonify(result)

@app.route('/clear_queue', methods=['POST'])
def clear_queue():
    """Clear upload queue"""
    result = batch_app.clear_upload_queue()
    return jsonify(result)

@app.route('/clear_results', methods=['POST'])
def clear_results():
    """Clear all results"""
    result = batch_app.clear_all_results()
    return jsonify(result)

@app.route('/process', methods=['POST'])
def process_images():
    """Start processing images"""
    data = request.get_json()
    positive_prompt = data.get('positive_prompt', batch_app.default_positive)
    negative_prompt = data.get('negative_prompt', batch_app.default_negative)
    save_unrefined = data.get('save_unrefined', True)  # Default to True for backward compatibility
    
    if not batch_app.upload_queue:
        return jsonify({"status": "error", "message": "No images in upload queue"})
    
    # Prepare image info list
    image_info_list = []
    processing_items = list(batch_app.upload_queue.items())
    
    for upload_id, info in processing_items:
        file_path = info['path']
        original_name = info['original_name']
        
        if os.path.exists(file_path):
            image_id = str(uuid.uuid4())
            image_info_list.append({
                'path': file_path,
                'original_name': original_name,
                'image_id': image_id
            })
            
            # Remove from upload queue as we are now processing it
            if upload_id in batch_app.upload_queue:
                del batch_app.upload_queue[upload_id]
    
    if not image_info_list:
        return jsonify({"status": "error", "message": "No valid files to process"})
    
    # Start processing in background thread
    def run_async_processing():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(
                batch_app.process_batch_with_live_updates(
                    image_info_list, positive_prompt, negative_prompt, save_unrefined
                )
            )
            
            # Emit final completion
            socketio.emit('batch_complete', {
                'total_processed': len(image_info_list),
                'completed': len([r for r in results if r]),
                'failed': len([r for r in results if not r])
            })
            
            # Clean up temp files
            for _, info in processing_items:
                temp_path = info['path']
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                        
        except Exception as e:
            print(f"Error during processing: {e}")
            socketio.emit('processing_error', {'error': str(e)})
        finally:
            loop.close()
    
    processing_thread = threading.Thread(target=run_async_processing)
    processing_thread.daemon = True
    processing_thread.start()
    
    return jsonify({"status": "success", "message": f"Started processing {len(image_info_list)} images"})

@app.route('/status')
def get_status():
    """Get current processing status"""
    status_data = batch_app.get_status_data()
    upload_queue = batch_app.get_upload_queue_images()
    results = batch_app.get_all_results()
    reprocess_queue = batch_app.get_reprocess_queue()
    
    # Get preview images for currently processing items
    preview_images = {}
    for image_id, preview in batch_app.preview_images.items():
        if image_id in batch_app.processing_status:
            status = batch_app.processing_status[image_id]
            if status.get('status') == 'processing':
                preview_images[image_id] = preview
    
    return jsonify({
        "status_data": status_data,
        "upload_queue": upload_queue,
        "results": results,
        "reprocess_queue": reprocess_queue,
        "queue_count": len(batch_app.upload_queue),
        "reprocess_count": len(batch_app.reprocess_queue),
        "preview_images": preview_images
    })

@app.route('/download_archive')
def download_archive():
    """Create and download archive of all results"""
    if not batch_app.results_cache:
        return jsonify({"status": "error", "message": "No results to archive"})
    
    # Check if we should include unrefined images
    include_unrefined = request.args.get('include_unrefined', 'true').lower() == 'true'
    
    # Filter results if needed
    results_to_archive = []
    for result in batch_app.results_cache.values():
        filtered_paths = []
        for output_path in result.get('output_paths', []):
            # Check if this is a refined image or if we're including all images
            if include_unrefined or '_refined' in output_path or 'refined-' in output_path:
                filtered_paths.append(output_path)
        
        if filtered_paths:
            result_copy = result.copy()
            result_copy['output_paths'] = filtered_paths
            results_to_archive.append(result_copy)
    
    if not results_to_archive:
        return jsonify({"status": "error", "message": "No images match the filter criteria"})
    
    archive_path = batch_app.create_archive(results_to_archive)
    
    return send_file(archive_path, as_attachment=True, download_name=Path(archive_path).name)

@app.route('/outputs/<path:filename>')
def serve_output_image(filename):
    """Serve output images"""
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename)

@app.route('/uploads/<path:filename>')
def serve_upload_image(filename):
    """Serve uploaded images"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/previews/<path:filename>')
def serve_preview_image(filename):
    """Serve preview images"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/delete_image/<image_id>')
def delete_image(image_id):
    """Delete a specific processed image"""
    if image_id in batch_app.results_cache:
        result = batch_app.results_cache[image_id]
        # Delete output files
        for output_path in result.get('output_paths', []):
            if os.path.exists(output_path):
                os.remove(output_path)
        del batch_app.results_cache[image_id]
        
        if image_id in batch_app.processing_status:
            del batch_app.processing_status[image_id]
        
        return jsonify({"status": "success", "message": f"Deleted image {image_id}"})
    
    return jsonify({"status": "error", "message": "Image not found"})

@app.route('/stop', methods=['POST'])
def stop_processing():
    """Stop the current batch processing"""
    batch_app.stop_processing = True
    return jsonify({
        "status": "success", 
        "message": "Stopping batch processing..."
    })

@app.route('/mark_reprocess/<image_id>', methods=['POST'])
def mark_reprocess(image_id):
    """Mark an image for re-processing"""
    result = batch_app.mark_for_reprocessing(image_id)
    return jsonify(result)

@app.route('/unmark_reprocess/<image_id>', methods=['POST'])
def unmark_reprocess(image_id):
    """Remove an image from re-processing queue"""
    result = batch_app.unmark_for_reprocessing(image_id)
    return jsonify(result)

@app.route('/clear_reprocess_queue', methods=['POST'])
def clear_reprocess_queue():
    """Clear all images from re-processing queue"""
    result = batch_app.clear_reprocess_queue()
    return jsonify(result)

@app.route('/reprocess', methods=['POST'])
def reprocess_images():
    """Start re-processing marked images"""
    data = request.get_json()
    positive_prompt = data.get('positive_prompt', batch_app.default_positive)
    negative_prompt = data.get('negative_prompt', batch_app.default_negative)
    save_unrefined = data.get('save_unrefined', True)
    
    if not batch_app.reprocess_queue:
        return jsonify({"status": "error", "message": "No images in re-processing queue"})
    
    # Prepare image info list from re-processing queue
    image_info_list = []
    reprocess_items = list(batch_app.reprocess_queue.items())
    
    for image_id, info in reprocess_items:
        file_path = info['path']
        original_name = info['original_name']
        
        if os.path.exists(file_path):
            # Create a new unique image ID for re-processing
            new_image_id = str(uuid.uuid4())
            image_info_list.append({
                'path': file_path,
                'original_name': original_name,
                'image_id': new_image_id,
                'is_reprocess': True,
                'original_image_id': image_id
            })
    
    if not image_info_list:
        return jsonify({"status": "error", "message": "No valid files to re-process"})
    
    # Clear the re-processing queue as we're now processing these images
    batch_app.reprocess_queue.clear()
    
    # Start processing in background thread
    def run_async_reprocessing():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(
                batch_app.process_batch_with_live_updates(
                    image_info_list, positive_prompt, negative_prompt, save_unrefined
                )
            )
            
            # Emit final completion
            socketio.emit('reprocess_complete', {
                'total_processed': len(image_info_list),
                'completed': len([r for r in results if r]),
                'failed': len([r for r in results if not r])
            })
            
            # Clean up temp files used for re-processing
            for _, info in reprocess_items:
                temp_path = info['path']
                if temp_path.startswith(str(batch_app.temp_input_dir)) and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                        
        except Exception as e:
            print(f"Error during re-processing: {e}")
            socketio.emit('processing_error', {'error': str(e)})
        finally:
            loop.close()
    
    reprocessing_thread = threading.Thread(target=run_async_reprocessing)
    reprocessing_thread.daemon = True
    reprocessing_thread.start()
    
    return jsonify({"status": "success", "message": f"Started re-processing {len(image_info_list)} images"})

# SocketIO Events
@socketio.on('connect')
def handle_connect():
    print('Client connected')
    emit('connected', {'data': 'Connected to server'})

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('join_monitoring')
def handle_join_monitoring():
    """Client wants to receive live updates"""
    join_room('monitoring')
    emit('joined', {'room': 'monitoring'})

if __name__ == '__main__':
    # Create required directories
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='ComfyUI Multi-GPU Batch Processor')
    parser.add_argument('--port', type=int, default=18384, help='Port to run the server on')
    args = parser.parse_args()
    
    # Run the app
    socketio.run(app, host='0.0.0.0', port=args.port, debug=False, allow_unsafe_werkzeug=True)