# Gradio App

import os
import json
import gradio as gr
import asyncio
import aiohttp
from pathlib import Path
from typing import List, Dict, Any, Tuple
import time
import shutil
import zipfile
from datetime import datetime
import threading
from queue import Queue
import uuid
import websocket
import base64
from PIL import Image
import io
import requests
import struct

# Import the ComfyUIMultiGPU class from batchProcess.py
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

class GradioComfyUIApp:
    def __init__(self):
        self.output_dir = Path("gradio_outputs")
        self.output_dir.mkdir(exist_ok=True)
        self.temp_input_dir = Path("temp_inputs")
        self.temp_input_dir.mkdir(exist_ok=True)
        
        # Load default prompts from workflow.json
        with open("workflow.json", 'r') as f:
            workflow = json.load(f)
        
        self.default_positive = workflow["10"]["inputs"]["text"]
        self.default_negative = workflow["15"]["inputs"]["text"]
        
        # Store processing results
        self.results_cache = {}
        self.processing_status = {}
        
        # Initialize orchestrator (will be created when processing starts)
        self.orchestrator = None
        self.comfyui_processes = []
        
        # Status update queue for live updates
        self.status_queue = Queue()
        
        # Initialize final status attributes
        self.final_status = None
        self.final_archive = None
        
        # Store preview images and websocket connections
        self.preview_images = {}
        self.ws_connections = {}
        self.uploaded_images = []  # Store uploaded images for viewing
        self.upload_queue = {}  # Store uploaded images with IDs for deletion
        
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
            
            self.orchestrator = ComfyUIMultiGPU(
                workflow_path="workflow.json",
                num_gpus=num_gpus,
                comfyui_path=comfyui_path,
                base_port=8200
            )
            # Start ComfyUI instances
            self.comfyui_processes = self.orchestrator.start_comfyui_instances()
            time.sleep(10)  # Wait for servers to initialize
    
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
                else:
                    # Text message - parse as JSON
                    data = json.loads(message)
                    
                    # Check for execution updates
                    if data.get('type') == 'executing':
                        node = data.get('data', {}).get('node')
                        if node is not None:
                            self.processing_status[image_id]['current_node'] = node
                    
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
            if image_id in self.ws_connections:
                del self.ws_connections[image_id]
            # Clean up preview image if exists
            if image_id in self.preview_images:
                preview = self.preview_images[image_id]
                if preview.startswith(str(self.temp_input_dir)):
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
    
    async def process_single_image_with_updates(self, session, gpu_id, image_path, 
                                               original_name,
                                               positive_prompt, negative_prompt, 
                                               image_id):
        """Process a single image and provide status updates"""
        server_url = f"http://localhost:{self.orchestrator.base_ports[gpu_id]}"
        
        try:
            # Verify input file exists
            if not os.path.exists(image_path):
                print(f"ERROR: Input file not found: {image_path}")
                self.processing_status[image_id] = {
                    'status': 'failed',
                    'error': 'Input file not found',
                    'gpu': gpu_id,
                    'filename': original_name
                }
                return None
            
            # Update status
            self.processing_status[image_id].update({
                'status': 'uploading',
                'gpu': gpu_id,
                'progress': 0,
                'filename': original_name,
                'current_node': None,
                'input_path': image_path
            })
            
            print(f"Calling orchestrator.upload_image_async for {original_name} (path: {image_path}) to server {server_url}")
            
            # Call the MODIFIED orchestrator.upload_image_async (which now uses API)
            upload_result = await self.orchestrator.upload_image_async(
                session, server_url, image_path, original_name
            )
            
            if not upload_result or 'name' not in upload_result:
                print(f"ERROR: Failed to upload {original_name} via API to {server_url}")
                self.processing_status[image_id]['status'] = 'failed'
                self.processing_status[image_id]['error'] = f"Upload failed via API. Server: {server_url}, File: {original_name}"
                return None
            
            print(f"API Upload for {original_name} successful, ComfyUI filename: {upload_result['name']}")
            
            # Modify workflow with custom prompts and the new filename from API
            workflow_copy = self.orchestrator.modify_workflow_for_image(
                upload_result['name']
            )
            
            # Update prompts in the workflow
            if "10" in workflow_copy:
                workflow_copy["10"]["inputs"]["text"] = positive_prompt
            if "15" in workflow_copy:
                workflow_copy["15"]["inputs"]["text"] = negative_prompt
            
            # Queue prompt
            self.processing_status[image_id]['status'] = 'processing'
            self.processing_status[image_id]['progress'] = 10
            
            # Generate client ID for websocket
            client_id = str(uuid.uuid4())
            
            # Start websocket monitoring before queuing
            self.monitor_progress_websocket(gpu_id, client_id, image_id)
            
            # Queue with client_id
            payload = {
                "prompt": workflow_copy,
                "client_id": client_id
            }
            
            async with session.post(f"{server_url}/prompt", json=payload) as resp:
                result = await resp.json()
            
            if not result or 'prompt_id' not in result:
                self.processing_status[image_id]['status'] = 'failed'
                return None
            
            prompt_id = result['prompt_id']
            
            # Poll for completion with progress updates
            start_time = time.time()
            timeout = 600
            
            while time.time() - start_time < timeout:
                history = await self.orchestrator.get_history_async(
                    session, server_url, prompt_id
                )
                
                if history and prompt_id in history:
                    prompt_history = history[prompt_id]
                    
                    # Update progress based on execution state
                    if prompt_history.get('status', {}).get('completed', False):
                        self.processing_status[image_id]['progress'] = 100
                        
                        # Get output images
                        outputs = prompt_history.get('outputs', {})
                        output_files = []
                        
                        # Download and save outputs with proper naming
                        base_name = Path(image_path).stem
                        
                        # Helper function to get unique filename
                        def get_unique_filename(base_path):
                            """Get a unique filename by appending numbers if needed"""
                            if not base_path.exists():
                                return base_path
                            
                            # Try appending numbers
                            counter = 1
                            while True:
                                new_path = base_path.parent / f"{base_path.stem}_{counter}{base_path.suffix}"
                                if not new_path.exists():
                                    return new_path
                                counter += 1
                        
                        # First output (node 20)
                        if "20" in outputs and 'images' in outputs["20"]:
                            for img_info in outputs["20"]['images']:
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
                                        
                                        # Save with new name, handling duplicates
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
                                        
                                        # Save with new name, handling duplicates
                                        output_path = get_unique_filename(self.output_dir / f"{base_name}_refined.png")
                                        with open(output_path, 'wb') as f:
                                            f.write(content)
                                        output_files.append(str(output_path))
                        
                        self.processing_status[image_id]['status'] = 'completed'
                        return {
                            'image_id': image_id,
                            'input_path': image_path,
                            'output_paths': output_files,
                            'status': 'completed'
                        }
                    
                    elif prompt_history.get('status', {}).get('status_str') == 'error':
                        self.processing_status[image_id]['status'] = 'error'
                        return None
                    else:
                        # Update progress during processing
                        execution = prompt_history.get('execution', {})
                        if execution:
                            current = execution.get('current', 0)
                            total = execution.get('total', 1)
                            progress = 25 + int((current / total) * 70)
                            self.processing_status[image_id]['progress'] = progress
                
                await asyncio.sleep(1)
            
            self.processing_status[image_id]['status'] = 'timeout'
            return None
            
        except Exception as e:
            self.processing_status[image_id]['status'] = 'error'
            self.processing_status[image_id]['error'] = str(e)
            return None
    
    async def process_batch_with_live_updates(self, image_info_list: List[Dict], 
                                            positive_prompt: str, 
                                            negative_prompt: str,
                                            progress_callback=None):
        """Process batch of images with live updates"""
        # image_info_list: List of dicts like [{'path': 'path/to/temp_image.png', 'original_name': 'user_image.png', 'image_id': 'uuid'}]
        
        # Ensure orchestrator is initialized
        if self.orchestrator is None:
            try:
                self.initialize_orchestrator()
            except Exception as e:
                print(f"Fatal: Failed to initialize orchestrator: {e}")
                # Update status for all images in batch to reflect this failure
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
                return [] # Return empty list as no processing can occur
        
        all_results_list = [] # Changed from results to avoid conflict with aiohttp ClientSession response variable name
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            
            for i, image_data in enumerate(image_info_list):
                gpu_id = i % self.orchestrator.num_gpus
                image_id = image_data['image_id']
                file_path = image_data['path']
                original_name = image_data['original_name']
                
                # Ensure processing_status has an entry for this image_id before calling process_single_image_with_updates
                # process_single_image_with_updates will then update it further.
                self.processing_status[image_id] = {
                    'filename': original_name,
                    'status': 'queued',
                    'gpu': gpu_id,
                    'progress': 0,
                    'input_path': file_path
                }
                
                print(f"Queuing {original_name} (ID: {image_id}) for GPU {gpu_id}")
                
                task = self.process_single_image_with_updates(
                    session, gpu_id, file_path, original_name, 
                    positive_prompt, negative_prompt, image_id
                )
                tasks.append(task)
            
            # Process with live updates
            completed_count = 0 # Renamed from completed to avoid conflict
            for task_future in asyncio.as_completed(tasks):
                try:
                    result_item = await task_future # result_item from process_single_image_with_updates
                    if result_item:
                        all_results_list.append(result_item)
                        # image_id should be in result_item for cache key
                        if 'image_id' in result_item:
                             self.results_cache[result_item['image_id']] = result_item
                             print(f"Completed processing for: {result_item.get('input_path', 'Unknown image')}")
                        else:
                            print(f"Warning: image_id missing from processing result for an image.")
                    else:
                        # Find corresponding image_id for failed task to update status display if needed
                        # This branch is for when process_single_image_with_updates returns None (e.g. upload failed)
                        # The status is already updated within process_single_image_with_updates.
                        print(f"A task for an image failed to complete or returned None.")
                    
                    completed_count += 1
                    if progress_callback:
                        progress_callback(completed_count, len(tasks))
                except Exception as e_task:
                    # This catches errors not handled within process_single_image_with_updates itself
                    print(f"Error processing an image task: {e_task}")
                    # Attempt to find which image_id this error belongs to is complex here.
                    # Status should be updated within process_single_image_with_updates preferably.
                    completed_count += 1
                    if progress_callback:
                        progress_callback(completed_count, len(tasks))
        
        return all_results_list
    
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
    
    def clear_result(self, image_id: str):
        """Clear a single result"""
        if image_id in self.results_cache:
            result = self.results_cache[image_id]
            # Delete output files
            for output_path in result.get('output_paths', []):
                if os.path.exists(output_path):
                    os.remove(output_path)
            del self.results_cache[image_id]
        
        if image_id in self.processing_status:
            del self.processing_status[image_id]
    
    def clear_all_results(self):
        """Clear all results and delete files"""
        # First delete all output files
        if self.output_dir.exists():
            for file_path in self.output_dir.glob("*.png"):
                try:
                    file_path.unlink()
                except Exception as e:
                    print(f"Error deleting {file_path}: {e}")
        
        # Clear caches
        self.results_cache.clear()
        self.processing_status.clear()
        self.preview_images.clear()
        
        # Close any open websockets
        for ws in self.ws_connections.values():
            try:
                ws.close()
            except:
                pass
        self.ws_connections.clear()
    
    def cleanup_gradio_temp_files(self):
        """Clean up Gradio's temporary upload files to prevent conflicts"""
        try:
            import tempfile
            temp_dir = tempfile.gettempdir()
            gradio_pattern = os.path.join(temp_dir, "gradio", "*")
            
            # Also check common gradio temp patterns
            patterns = [
                os.path.join(temp_dir, "gradio", "*"),
                os.path.join(temp_dir, "tmp*", "gradio", "*"),
                os.path.join(temp_dir, "*.tmp")
            ]
            
            cleaned = 0
            for pattern in patterns:
                try:
                    import glob
                    for temp_file in glob.glob(pattern):
                        if os.path.isfile(temp_file):
                            age = time.time() - os.path.getmtime(temp_file)
                            # Only delete files older than 60 seconds to avoid conflicts
                            if age > 60:
                                try:
                                    os.remove(temp_file)
                                    cleaned += 1
                                except:
                                    pass
                except:
                    pass
            
            if cleaned > 0:
                print(f"Cleaned up {cleaned} old temporary files")
                
        except Exception as e:
            print(f"Temp cleanup error: {e}")
    
    def add_to_upload_queue(self, files):
        """Handle file uploads - single or multiple"""
        if not files:
            return self.get_upload_queue_images(), gr.update(value=None), "No files to upload.", f"{len(self.upload_queue)} images in queue"

        # Ensure temp_input_dir exists
        self.temp_input_dir.mkdir(exist_ok=True)
        
        # Convert to list if single file
        file_list = files if isinstance(files, list) else [files]
        
        successful_uploads = 0
        failed_uploads = []
        
        # Process each file
        for i, file_obj in enumerate(file_list):
            try:
                # Get the file path - Gradio provides this in the 'name' attribute
                if hasattr(file_obj, 'name'):
                    source_path = file_obj.name
                elif isinstance(file_obj, str):
                    source_path = file_obj
                elif isinstance(file_obj, dict) and 'name' in file_obj:
                    source_path = file_obj['name']
                else:
                    failed_uploads.append(f"File {i+1} (invalid format)")
                    continue
                
                # Verify file exists
                if not os.path.exists(source_path):
                    failed_uploads.append(f"File {i+1} (not found)")
                    continue
                
                # Get original filename
                original_name = None
                if hasattr(file_obj, 'orig_name'):
                    original_name = os.path.basename(file_obj.orig_name)
                elif isinstance(file_obj, dict) and 'orig_name' in file_obj:
                    original_name = os.path.basename(file_obj['orig_name'])
                
                if not original_name:
                    original_name = os.path.basename(source_path)
                
                # Create unique ID
                upload_id = str(uuid.uuid4())
                dest_filename = f"{upload_id}_{original_name}"
                dest_path = self.temp_input_dir / dest_filename
                
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
                
                # Copy file
                try:
                    shutil.copy2(source_path, dest_path)
                    
                    # Verify copy
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
                    print(f"Copy error for {original_name}: {e}")
                    failed_uploads.append(original_name)
                    
            except Exception as e:
                print(f"Error processing file {i+1}: {e}")
                failed_uploads.append(f"File {i+1}")
        
        # Status message
        if successful_uploads == len(file_list):
            status_msg = f"✓ Successfully uploaded {successful_uploads} image(s)"
        elif successful_uploads > 0:
            status_msg = f"⚠️ Uploaded {successful_uploads}/{len(file_list)} images. Failed: {', '.join(failed_uploads)}"
        else:
            status_msg = f"❌ Failed to upload any images"
        
        queue_count = f"{len(self.upload_queue)} images in queue"
        return self.get_upload_queue_images(), gr.update(value=None), status_msg, queue_count
    
    def get_upload_queue_images(self):
        """Get list of image paths for gallery display"""
        return [info['path'] for info in self.upload_queue.values()]
    
    def remove_from_upload_queue(self, upload_id):
        """Remove a specific image from the upload queue"""
        if upload_id in self.upload_queue:
            # Delete the temp file
            temp_path = self.upload_queue[upload_id]['path']
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            
            # Remove from queue
            del self.upload_queue[upload_id]
        
        return self.get_upload_queue_images()
    
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
        return self.get_upload_queue_images()
    
    def get_all_results(self):
        """Get all processed images for gallery display"""
        all_images = []
        for result in self.results_cache.values():
            all_images.extend(result.get('output_paths', []))
        return all_images
    
    def load_existing_results(self):
        """Load existing results from output directory on startup"""
        if not self.output_dir.exists():
            return
        
        # Group files by base name
        file_groups = {}
        for file_path in self.output_dir.glob("*.png"):
            if file_path.stem.endswith("_refined"):
                base_name = file_path.stem[:-8]  # Remove "_refined"
                file_type = "refined"
            elif file_path.stem.endswith("_"):
                base_name = file_path.stem[:-1]  # Remove "_"
                file_type = "base"
            else:
                continue
            
            if base_name not in file_groups:
                file_groups[base_name] = {}
            file_groups[base_name][file_type] = str(file_path)
        
        # Create result entries for existing files
        for base_name, files in file_groups.items():
            image_id = str(uuid.uuid4())
            output_paths = []
            if "base" in files:
                output_paths.append(files["base"])
            if "refined" in files:
                output_paths.append(files["refined"])
            
            if output_paths:
                self.results_cache[image_id] = {
                    'image_id': image_id,
                    'input_path': f"{base_name}.png",  # Approximate
                    'output_paths': output_paths,
                    'status': 'completed'
                }
                
                self.processing_status[image_id] = {
                    'filename': f"{base_name}.png",
                    'status': 'completed',
                    'gpu': -1,
                    'progress': 100
                }
    
    def delete_image(self, image_path):
        """Delete a specific image"""
        if not image_path:
            return self.get_all_results(), "No image specified"
        
        # Find and remove the result containing this image
        removed = False
        for image_id, result in list(self.results_cache.items()):
            if image_path in result.get('output_paths', []):
                self.clear_result(image_id)
                removed = True
                break
        
        if removed:
            return self.get_all_results(), f"Deleted: {Path(image_path).name}"
        else:
            return self.get_all_results(), "Image not found"
    
    def generate_gallery_html(self):
        """Generate HTML for image gallery with delete buttons"""
        images = self.get_all_results()
        if not images:
            return "<p>No images to display</p>"
        
        html = '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; padding: 20px;">'
        
        for i, img_path in enumerate(images):
            img_name = Path(img_path).name
            # Convert path to URL format
            img_url = f"/file={img_path}"
            
            html += f'''
            <div style="border: 1px solid #ddd; border-radius: 8px; padding: 10px; background: #f9f9f9;">
                <img src="{img_url}" style="width: 100%; height: auto; border-radius: 4px; margin-bottom: 10px;" />
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 12px; color: #666; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{img_name}</span>
                    <button onclick="delete_image('{img_path}')" style="background: #ff4444; color: white; border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer;">🗑️</button>
                </div>
            </div>
            '''
        
        html += '</div>'
        return html
    
    def rerun_failed_images(self, positive_prompt, negative_prompt):
        """Rerun only failed images"""
        failed_images = []
        failed_items = []
        
        for image_id, status in self.processing_status.items():
            if status['status'] in ['failed', 'error', 'timeout']:
                # Find original input path from status
                input_path = status.get('input_path')
                if input_path and os.path.exists(input_path):
                    # Add back to upload queue
                    upload_id = str(uuid.uuid4())
                    original_name = Path(input_path).name
                    
                    self.upload_queue[upload_id] = {
                        'path': input_path,
                        'original_name': original_name,
                        'upload_time': time.time()
                    }
                    failed_items.append((upload_id, self.upload_queue[upload_id]))
        
        if not failed_items:
            return self.get_all_results(), "No failed images to rerun", None, self.get_upload_queue_images()
        
        # Clear failed results first
        for image_id in list(self.processing_status.keys()):
            if self.processing_status[image_id]['status'] in ['failed', 'error', 'timeout']:
                self.clear_result(image_id)
        
        # Process failed images (they're now in the upload queue)
        return self.process_images(None, positive_prompt, negative_prompt)
    
    def process_images(self, files, positive_prompt, negative_prompt, progress=gr.Progress()):
        """Main processing function for Gradio"""
        # Ensure orchestrator is initialized if not already (e.g. if pre-warming failed)
        if self.orchestrator is None:
            try:
                print("Orchestrator not initialized. Attempting to initialize now...")
                self.initialize_orchestrator()
                print("Orchestrator initialized successfully for processing.")
            except Exception as e_orch_init:
                error_msg = f"FATAL: Orchestrator could not be initialized: {e_orch_init}. Cannot process images."
                print(error_msg)
                # Clear upload queue as we cannot process them
                upload_queue_items_to_clear = list(self.upload_queue.keys())
                for item_id_clear in upload_queue_items_to_clear:
                    if item_id_clear in self.upload_queue and 'path' in self.upload_queue[item_id_clear]:
                        path_to_delete = self.upload_queue[item_id_clear]['path']
                        if os.path.exists(path_to_delete):
                            try:
                                os.remove(path_to_delete)
                            except Exception:
                                pass
                    if item_id_clear in self.upload_queue: del self.upload_queue[item_id_clear]
                return self.get_all_results(), error_msg, None, self.get_upload_queue_images()

        # Use images from upload queue instead of file input
        if not self.upload_queue:
            return self.get_all_results(), "No images in upload queue. Please upload images first.", None, []
        
        # Get file paths from upload queue
        image_info_list = []
        processing_items_for_cleanup = [] # Tuples of (upload_id, info_dict)
        
        # Take images from the queue
        # Create a copy of items to iterate over, as we modify self.upload_queue
        items_to_process_from_queue = list(self.upload_queue.items())
        
        print(f"Preparing {len(items_to_process_from_queue)} images from upload queue for processing...")
        
        for upload_id, info in items_to_process_from_queue:
            file_path = info['path'] # Path in temp_inputs
            original_name = info['original_name']
            
            if os.path.exists(file_path):
                image_id = str(uuid.uuid4()) # Generate image_id for this processing run
                image_info_list.append({
                    'path': file_path,
                    'original_name': original_name,
                    'image_id': image_id
                })
                processing_items_for_cleanup.append((upload_id, info)) # Store for deleting from temp_inputs later
                
                # Remove from upload queue as we are now processing it
                if upload_id in self.upload_queue: # Check existence before deleting
                    del self.upload_queue[upload_id]
            else:
                print(f"Warning: File not found in upload queue (was at {file_path}) for {original_name}. Skipping.")
                # Also remove from queue if path is invalid
                if upload_id in self.upload_queue:
                    del self.upload_queue[upload_id]
        
        print(f"Successfully prepared {len(image_info_list)} files for processing.")
        updated_upload_queue_display = self.get_upload_queue_images() # Get images remaining in queue
        
        if not image_info_list:
            return self.get_all_results(), "No valid files to process from the queue.", None, updated_upload_queue_display
        
        # Start processing in background
        progress(0, desc="Starting processing...")
        status_msg = f"Processing {len(image_info_list)} images..."
        
        # Create a thread to handle the async processing
        def run_async_processing():
            def progress_callback(current, total):
                progress(current / total, desc=f"Processing {current}/{total} images...")
            
            try:
                # Run async processing
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                # Results from process_batch_with_live_updates
                batch_results = loop.run_until_complete(
                    self.process_batch_with_live_updates(
                        image_info_list, positive_prompt, negative_prompt, progress_callback
                    )
                )
                loop.close()
                
                # Update final status after completion
                # Count based on self.processing_status which is updated by individual tasks
                completed_final_count = 0
                failed_final_count = 0
                for img_id_chk in [info['image_id'] for info in image_info_list]: # Check status for all images attempted in this batch
                    if img_id_chk in self.processing_status:
                        if self.processing_status[img_id_chk]['status'] == 'completed':
                            completed_final_count += 1
                        elif self.processing_status[img_id_chk]['status'] in ['failed', 'error', 'timeout']:
                            failed_final_count += 1
                    else:
                        # Should not happen if image_id was correctly propagated
                        failed_final_count += 1 

                self.final_status = f"Batch complete. Processed: {len(image_info_list)}. Completed: {completed_final_count}, Failed: {failed_final_count}"
                print(self.final_status)
                
                # Create archive if there are any results in the cache
                if self.get_all_results(): # Checks self.results_cache
                    self.final_archive = self.create_archive(list(self.results_cache.values()))
                else:
                    self.final_archive = None
                    
                # Clean up processed temp files (from temp_inputs, which were originally from Gradio upload)
                print(f"Cleaning up {len(processing_items_for_cleanup)} staged temporary files...")
                for _upload_id_processed, info_processed in processing_items_for_cleanup:
                    temp_path_to_clean = info_processed['path']
                    if os.path.exists(temp_path_to_clean):
                        try:
                            os.remove(temp_path_to_clean)
                            print(f"Cleaned up temp file: {temp_path_to_clean}")
                        except Exception as e_clean:
                            print(f"Error cleaning temp file {temp_path_to_clean}: {e_clean}")
                            
            except Exception as e_async_run:
                error_str = f"Error during async processing run: {str(e_async_run)}"
                print(error_str)
                self.final_status = error_str
                self.final_archive = None
                import traceback
                traceback.print_exc()
        
        # Start processing thread
        import threading
        processing_thread = threading.Thread(target=run_async_processing)
        processing_thread.daemon = True
        processing_thread.start()
        
        # Small delay to ensure thread has started and UI can update for queue changes
        time.sleep(0.2)
        
        # Return immediately with current state and updated upload queue display
        return self.get_all_results(), status_msg, None, updated_upload_queue_display
    
    def get_status_df(self):
        """Get processing status as dataframe for display"""
        import pandas as pd
        
        if not self.processing_status:
            return pd.DataFrame(columns=['Filename', 'Status', 'GPU', 'Progress'])
        
        data = []
        for image_id, status in self.processing_status.items():
            status_str = status.get('status', 'Unknown')
            # Add error info if available
            if status_str == 'failed' and 'error' in status:
                status_str = f"failed: {status['error']}"
            
            data.append({
                'Filename': status.get('filename', 'Unknown'),
                'Status': status_str,
                'GPU': status.get('gpu', -1),
                'Progress': f"{status.get('progress', 0)}%"
            })
        
        # Sort by GPU and status
        df = pd.DataFrame(data)
        if not df.empty:
            df = df.sort_values(['GPU', 'Status'])
        
        return df

# Create the Gradio interface
def create_interface():
    app = GradioComfyUIApp()
    
    # Load existing results on startup
    app.load_existing_results()
    
    with gr.Blocks(title="ComfyUI Batch Processor", css="""
        .gallery-item { border: 2px solid transparent; }
        .gallery-item.selected { border: 2px solid #1976d2; }
    """) as interface:
        gr.Markdown("# ComfyUI Multi-GPU Batch Processor")
        gr.Markdown(f"Detected CUDA devices: {app.detect_cuda_devices()}")
        
        with gr.Row():
            with gr.Column(scale=1):
                # Input section - SIMPLIFIED APPROACH
                gr.Markdown("### Upload Images")
                gr.Markdown("**Option 1: Drag and drop a folder of images**")
                file_input = gr.File(
                    label="Upload Images (try one at a time if multiple fails)",
                    file_count="multiple",
                    file_types=["image"],
                    interactive=True
                )
                
                gr.Markdown("**Option 2: Paste file paths (one per line)**")
                file_paths_input = gr.Textbox(
                    label="File Paths",
                    placeholder="C:\\path\\to\\image1.png\nC:\\path\\to\\image2.jpg\n...",
                    lines=5,
                    interactive=True
                )
                
                with gr.Row():
                    add_paths_btn = gr.Button("Add Paths to Queue", variant="secondary")
                    scan_folder_btn = gr.Button("Scan Folder", variant="secondary")
                
                folder_path_input = gr.Textbox(
                    label="Folder Path (for scanning)",
                    placeholder="C:\\path\\to\\folder",
                    interactive=True
                )
                
                # Upload status
                upload_status = gr.Textbox(
                    label="Upload Status",
                    value="Ready to upload images",
                    interactive=False,
                    visible=True
                )
                
                # Show uploaded images gallery
                gr.Markdown("### Upload Queue")
                uploaded_gallery = gr.Gallery(
                    label="Images ready to process",
                    show_label=False,
                    columns=4,
                    rows=2,
                    height=200,
                    object_fit="contain",
                    value=app.get_upload_queue_images()
                )
                
                # Add upload counter
                upload_counter = gr.Textbox(
                    label="Queue Status",
                    value=f"0 images in queue",
                    interactive=False
                )
                
                positive_prompt = gr.Textbox(
                    label="Positive Prompt",
                    value=app.default_positive,
                    lines=2
                )
                
                negative_prompt = gr.Textbox(
                    label="Negative Prompt", 
                    value=app.default_negative,
                    lines=2
                )
                
                with gr.Row():
                    process_btn = gr.Button("Process Images", variant="primary")
                    rerun_btn = gr.Button("Rerun Failed", variant="secondary")
                
                with gr.Row():
                    clear_all_btn = gr.Button("Clear All Results", variant="stop")
                    clear_queue_btn = gr.Button("Clear Upload Queue", variant="secondary")
                    refresh_btn = gr.Button("🔄 Refresh Status", variant="secondary")
                
                # Debug section
                with gr.Accordion("Debug Info", open=False):
                    debug_output = gr.Textbox(
                        label="Debug Output",
                        lines=10,
                        max_lines=20,
                        interactive=False
                    )
                    test_connection_btn = gr.Button("Test ComfyUI Connection")
                
                # Status display
                status_text = gr.Textbox(label="Status", interactive=False)
                
                status_df = gr.Dataframe(
                    label="Processing Status",
                    headers=["Filename", "Status", "GPU", "Progress"],
                    interactive=False,
                    max_rows=10
                )
                
                # Add manual upload button
                with gr.Row():
                    upload_btn = gr.Button("Add to Queue", variant="secondary", scale=1)
                    clear_files_btn = gr.Button("Clear Selection", scale=1)
            
            with gr.Column(scale=2):
                # Live preview section
                gr.Markdown("### Live Generation Preview")
                preview_gallery = gr.Gallery(
                    label="Currently Processing",
                    show_label=False,
                    columns=4,
                    rows=2,
                    height=300,
                    object_fit="contain",
                    value=[]
                )
                
                # Results section
                gr.Markdown("### Completed Images")
                gallery = gr.Gallery(
                    label="Processed Images",
                    show_label=False,
                    columns=2,
                    height="auto",
                    object_fit="contain",
                    allow_preview=True,
                    interactive=False
                )
                
                with gr.Row():
                    download_btn = gr.File(
                        label="Download Archive",
                        interactive=False
                    )
                    create_archive_btn = gr.Button("Create New Archive", variant="secondary")
                
                # Delete functionality
                gr.Markdown("### Delete Individual Images")
                with gr.Row():
                    image_dropdown = gr.Dropdown(
                        label="Select image to delete",
                        choices=[],
                        interactive=True
                    )
                    delete_btn = gr.Button("Delete Selected", variant="stop", scale=0)
        
        # Initialize gallery with existing results
        initial_images = app.get_all_results()
        if initial_images:
            gallery.value = initial_images
            status_text.value = f"Loaded {len(initial_images)} existing images"
        
        # Auto-refresh status
        def refresh_status_and_gallery():
            df = app.get_status_df()
            images = app.get_all_results()
            
            # Get live preview images
            preview_images = []
            preview_ids = []  # Track which images we're showing
            
            # Get previews for all currently processing images
            for image_id, status in app.processing_status.items():
                if status['status'] == 'processing' and image_id in app.preview_images:
                    preview = app.preview_images[image_id]
                    try:
                        # Check if it's a file path or URL
                        if os.path.exists(preview):
                            # Local file - add directly
                            preview_images.append(preview)
                            preview_ids.append(image_id)
                        else:
                            # URL - fetch the preview image
                            response = requests.get(preview, timeout=0.5)
                            if response.status_code == 200:
                                # Save temporarily and add to previews
                                temp_preview = app.temp_input_dir / f"live_preview_{image_id}.png"
                                with open(temp_preview, 'wb') as f:
                                    f.write(response.content)
                                preview_images.append(str(temp_preview))
                                preview_ids.append(image_id)
                    except Exception:
                        pass
            
            # Show placeholder for processing images without previews yet
            for image_id, status in app.processing_status.items():
                if status['status'] == 'processing' and image_id not in preview_ids:
                    # Add a placeholder or status text
                    progress = status.get('progress', 0)
                    node = status.get('current_node', 'preparing')
                    filename = status.get('filename', 'unknown')
                    # Could add a generated placeholder image here
            
            # Clean up old preview files
            try:
                for pattern in ["preview_*", "temp_preview_*", "live_preview_*"]:
                    for temp_file in app.temp_input_dir.glob(pattern):
                        # Remove files older than 30 seconds
                        if temp_file.stat().st_mtime < time.time() - 30:
                            try:
                                temp_file.unlink()
                            except:
                                pass
            except:
                pass
            
            # Update status message if processing is complete
            if hasattr(app, 'final_status'):
                status = app.final_status
                archive = getattr(app, 'final_archive', None)
            else:
                # Check if any processing is happening
                processing = [s for s in app.processing_status.values() 
                            if s['status'] in ['processing', 'queued', 'uploading']]
                if processing:
                    # Show detailed status
                    status_parts = []
                    for s in processing:
                        node = s.get('current_node', 'preparing')
                        progress = s.get('progress', 0)
                        filename = s.get('filename', 'unknown')
                        status_parts.append(f"{filename}: {progress}% ({node})")
                    status = "Processing:\n" + "\n".join(status_parts[:5])  # Show max 5
                    archive = None
                else:
                    status = status_text.value if status_text.value else "Ready"
                    archive = download_btn.value
            
            # Update dropdown choices with image names
            choices = [(Path(img).name, img) for img in images]
            
            # Get current upload queue images
            upload_queue_images = app.get_upload_queue_images()
            queue_count = f"{len(app.upload_queue)} images in queue"
            
            return df, preview_images, images, status, archive, gr.update(choices=choices), upload_queue_images, queue_count
        
        # Event handlers
        def handle_file_upload(files):
            """Handle file upload with progress updates"""
            if not files:
                return app.get_upload_queue_images(), gr.update(value=None), "No files selected", f"{len(app.upload_queue)} images in queue"
            
            # Process files
            gallery_images, file_update, status_msg, queue_count = app.add_to_upload_queue(files)
            
            return gallery_images, file_update, status_msg, queue_count
        
        def handle_file_paths(paths_text):
            """Handle file paths pasted as text"""
            if not paths_text:
                return app.get_upload_queue_images(), "No paths provided", f"{len(app.upload_queue)} images in queue"
            
            # Split paths and create file-like objects
            paths = [p.strip() for p in paths_text.split('\n') if p.strip()]
            valid_paths = []
            
            for path in paths:
                if os.path.exists(path) and os.path.isfile(path):
                    # Check if it's an image
                    if path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')):
                        valid_paths.append(path)
            
            if not valid_paths:
                return app.get_upload_queue_images(), "No valid image paths found", f"{len(app.upload_queue)} images in queue"
            
            # Process the paths
            gallery_images, _, status_msg, queue_count = app.add_to_upload_queue(valid_paths)
            
            return gallery_images, status_msg, queue_count
        
        def scan_folder(folder_path):
            """Scan a folder for images"""
            if not folder_path or not os.path.exists(folder_path):
                return "", "Invalid folder path"
            
            image_paths = []
            extensions = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')
            
            # Scan folder
            for file in Path(folder_path).iterdir():
                if file.is_file() and file.suffix.lower() in extensions:
                    image_paths.append(str(file))
            
            if image_paths:
                return '\n'.join(image_paths), f"Found {len(image_paths)} images"
            else:
                return "", "No images found in folder"
        
        # Enable automatic upload on file change
        file_input.change(
            fn=handle_file_upload,
            inputs=[file_input],
            outputs=[uploaded_gallery, file_input, upload_status, upload_counter]
        )
        
        # Manual upload button
        upload_btn.click(
            fn=handle_file_upload,
            inputs=[file_input],
            outputs=[uploaded_gallery, file_input, upload_status, upload_counter]
        )
        
        # Add paths button
        add_paths_btn.click(
            fn=handle_file_paths,
            inputs=[file_paths_input],
            outputs=[uploaded_gallery, upload_status, upload_counter]
        )
        
        # Scan folder button
        scan_folder_btn.click(
            fn=scan_folder,
            inputs=[folder_path_input],
            outputs=[file_paths_input, upload_status]
        )
        
        clear_files_btn.click(
            fn=lambda: (gr.update(value=None), "Files cleared"),
            outputs=[file_input, upload_status]
        )
        
        process_btn.click(
            fn=app.process_images,
            inputs=[file_input, positive_prompt, negative_prompt],
            outputs=[gallery, status_text, download_btn, uploaded_gallery]
        )
        
        rerun_btn.click(
            fn=app.rerun_failed_images,
            inputs=[positive_prompt, negative_prompt],
            outputs=[gallery, status_text, download_btn, uploaded_gallery]
        )
        
        def clear_all_and_refresh():
            app.clear_all_results()
            app.clear_upload_queue()  # Also clear upload queue
            return [], "All results cleared", None, [], "0 images in queue"
            
        clear_all_btn.click(
            fn=clear_all_and_refresh,
            outputs=[gallery, status_text, download_btn, uploaded_gallery, upload_counter]
        )
        
        def clear_queue_and_update():
            images = app.clear_upload_queue()
            return images, "0 images in queue"
        
        clear_queue_btn.click(
            fn=clear_queue_and_update,
            outputs=[uploaded_gallery, upload_counter]
        )
        
        create_archive_btn.click(
            fn=lambda: app.create_archive(list(app.results_cache.values())) 
                       if app.results_cache else None,
            outputs=[download_btn]
        )
        
        delete_btn.click(
            fn=app.delete_image,
            inputs=[image_dropdown],
            outputs=[gallery, status_text]
        )
        
        def test_comfyui_connection():
            """Test connection to ComfyUI servers"""
            debug_info = []
            debug_info.append(f"ComfyUI Path: {getattr(app.orchestrator, 'comfyui_path', 'Not initialized')}")
            debug_info.append(f"Number of GPUs: {app.detect_cuda_devices()}")
            debug_info.append("")
            
            if app.orchestrator:
                debug_info.append("Testing ComfyUI servers:")
                for i, port in enumerate(app.orchestrator.base_ports):
                    url = f"http://localhost:{port}"
                    if app.orchestrator.check_server(url):
                        debug_info.append(f"✓ GPU {i} - Port {port}: Running")
                    else:
                        debug_info.append(f"✗ GPU {i} - Port {port}: Not responding")
                
                # Test input directory
                input_dir = os.path.join(app.orchestrator.comfyui_path, "input")
                if os.path.exists(input_dir):
                    debug_info.append(f"\n✓ Input directory exists: {input_dir}")
                    # Check write permissions
                    try:
                        test_file = os.path.join(input_dir, "test_write.txt")
                        with open(test_file, 'w') as f:
                            f.write("test")
                        os.remove(test_file)
                        debug_info.append("✓ Write permissions OK")
                    except Exception as e:
                        debug_info.append(f"✗ Write permission error: {e}")
                else:
                    debug_info.append(f"\n✗ Input directory not found: {input_dir}")
            else:
                debug_info.append("✗ Orchestrator not initialized")
            
            return "\n".join(debug_info)
        
        test_connection_btn.click(
            fn=test_comfyui_connection,
            outputs=[debug_output]
        )
        
        refresh_btn.click(
            fn=refresh_status_and_gallery,
            outputs=[status_df, preview_gallery, gallery, status_text, download_btn, image_dropdown, uploaded_gallery, upload_counter]
        )
        
        # Set up auto-refresh with native Gradio support
        interface.load(
            fn=refresh_status_and_gallery,
            outputs=[status_df, preview_gallery, gallery, status_text, download_btn, image_dropdown, uploaded_gallery, upload_counter],
            every=1  # Auto-refresh every 1 second
        )
    
    return interface

if __name__ == "__main__":
    interface = create_interface()
    interface.queue(concurrency_count=1, max_size=50)  # Serialize uploads to prevent race conditions
    
    # Get port from environment or use default
    port = 18384
    
    interface.launch(
        server_name="0.0.0.0",
        server_port=port,
        share=False,
        inbrowser=False,  # Don't auto-open browser in server environment
        max_threads=40,  # Increase max threads for better concurrent handling
        file_directories=[str(Path("temp_inputs").absolute()), str(Path("gradio_outputs").absolute())]  # Allow access to our directories
    )
