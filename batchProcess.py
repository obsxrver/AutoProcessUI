#!/usr/bin/env python

import os
import json
import requests
import asyncio
import aiohttp
from pathlib import Path
from typing import List, Dict, Any
import time
import subprocess
import sys
import mimetypes

class ComfyUIMultiGPU:
    def __init__(self, workflow_path: str, num_gpus: int = 8, comfyui_path: str = "/workspace/ComfyUI", base_port: int = 8200):
        self.workflow_path = workflow_path
        self.num_gpus = num_gpus
        self.comfyui_path = comfyui_path
        self.base_ports = list(range(base_port, base_port + num_gpus))  # 8200, 8201, ..., 8207
        
        # Load the workflow (already in API format)
        with open(workflow_path, 'r') as f:
            self.workflow = json.load(f)
    
    def start_comfyui_instances(self):
        """Start ComfyUI instances on different GPUs"""
        processes = []
        
        # Check if servers are already running
        already_running = []
        for i, port in enumerate(self.base_ports):
            if self.check_server(f"http://localhost:{port}"):
                already_running.append(i)
                print(f"ComfyUI already running on port {port} (GPU {i})")
        
        if already_running:
            print(f"Found {len(already_running)} existing ComfyUI instances. Using those.")
            if len(already_running) >= self.num_gpus:
                return []  # Don't start new processes
        
        for i in range(self.num_gpus):
            if i in already_running:
                continue  # Skip if already running
                
            env = os.environ.copy()
            env['CUDA_VISIBLE_DEVICES'] = str(i)
            
            cmd = [
                sys.executable,  # Use the same Python interpreter
                os.path.join(self.comfyui_path, 'main.py'),
                '--port', str(self.base_ports[i]),
                '--highvram',
                '--disable-auto-launch',
                '--listen', '0.0.0.0'  # Allow connections from any IP
            ]
            
            print(f"Starting ComfyUI on GPU {i}, port {self.base_ports[i]}")
            process = subprocess.Popen(
                cmd, 
                env=env,
                cwd=self.comfyui_path,  # Run from ComfyUI directory
                stdout=subprocess.DEVNULL,  # Suppress output for cleaner logs
                stderr=subprocess.DEVNULL
            )
            processes.append(process)
        
        # Wait for servers to start with progressive checking
        print("Waiting for servers to initialize...")
        max_wait = 60  # Maximum 60 seconds
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            all_running = True
            for i, port in enumerate(self.base_ports):
                if not self.check_server(f"http://localhost:{port}"):
                    all_running = False
                    break
            
            if all_running:
                print("All servers are running!")
                break
            
            time.sleep(2)
        
        # Final check and report
        for i, port in enumerate(self.base_ports):
            if not self.check_server(f"http://localhost:{port}"):
                print(f"Warning: Server on port {port} (GPU {i}) may not be running properly")
        
        return processes
    
    def check_server(self, server_url: str, timeout: int = 5) -> bool:
        """Check if a ComfyUI server is running"""
        try:
            response = requests.get(f"{server_url}/system_stats", timeout=timeout)
            return response.status_code == 200
        except:
            return False
    
    async def upload_image_async(self, session: aiohttp.ClientSession, 
                                server_url: str, image_path: str, original_filename: str) -> Dict:
        """Upload an image to a ComfyUI server's /upload/image API endpoint."""
        file_handle = None
        try:
            if not os.path.exists(image_path):
                print(f"Error: Source file not found for API upload: {image_path}")
                return None

            # Get file size for debugging
            file_size = os.path.getsize(image_path)
            print(f"Uploading {original_filename} ({file_size} bytes) from {image_path}")

            form_data = aiohttp.FormData()
            
            content_type, _ = mimetypes.guess_type(image_path)
            if content_type is None:
                content_type = 'application/octet-stream' # Fallback

            # Open file in binary mode
            file_handle = open(image_path, 'rb')
            
            form_data.add_field(
                'image',
                file_handle,
                filename=original_filename, # ComfyUI uses this to suggest a name
                content_type=content_type
            )
            # Optionally, add 'overwrite': 'true' or 'false' if needed
            # form_data.add_field('overwrite', 'true')

            # The ComfyUI /upload/image API endpoint
            upload_url = f"{server_url}/upload/image"
            
            print(f"Uploading to {upload_url} via API")

            async with session.post(upload_url, data=form_data) as resp:
                if resp.status == 200:
                    upload_response = await resp.json()
                    # Expected response: {"name": "filename.png", "subfolder": "", "type": "input"}
                    print(f"Successfully uploaded {original_filename} via API: {upload_response}")
                    return upload_response 
                else:
                    error_text = await resp.text()
                    print(f"Error uploading image {original_filename} via API to {upload_url}: {resp.status} - {error_text}")
                    return None
                
        except Exception as e:
            print(f"Error in upload_image_async (API for {original_filename}): {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            # Always close the file handle
            if file_handle:
                file_handle.close()
    
    async def queue_prompt_async(self, session: aiohttp.ClientSession, 
                                server_url: str, prompt: Dict[str, Any]) -> Dict:
        """Queue a prompt on a specific ComfyUI instance"""
        try:
            # Generate a unique client_id for this request
            import uuid
            client_id = str(uuid.uuid4())
            
            payload = {
                "prompt": prompt,
                "client_id": client_id
            }
            
            async with session.post(f"{server_url}/prompt", json=payload) as resp:
                result = await resp.json()
                return result
        except Exception as e:
            print(f"Error queuing prompt on {server_url}: {e}")
            return None
    
    async def get_history_async(self, session: aiohttp.ClientSession, 
                               server_url: str, prompt_id: str) -> Dict:
        """Get the history for a specific prompt"""
        try:
            async with session.get(f"{server_url}/history/{prompt_id}") as resp:
                return await resp.json()
        except Exception as e:
            print(f"Error getting history from {server_url}: {e}")
            return None
    
    async def wait_for_completion_async(self, session: aiohttp.ClientSession,
                                      server_url: str, prompt_id: str) -> Dict:
        """Wait for a prompt to complete and return the result (no timeout)"""
        
        while True:
            history = await self.get_history_async(session, server_url, prompt_id)
            
            if history and prompt_id in history:
                prompt_history = history[prompt_id]
                if prompt_history.get('status', {}).get('completed', False):
                    return {
                        'status': 'completed',
                        'outputs': prompt_history.get('outputs', {})
                    }
                elif prompt_history.get('status', {}).get('status_str') == 'error':
                    return {
                        'status': 'error',
                        'error': prompt_history.get('status', {}).get('messages', [])
                    }
            
            await asyncio.sleep(2)
    
    def modify_workflow_for_image(self, image_filename: str) -> Dict:
        """Modify the workflow to use a specific image"""
        # Create a deep copy of the workflow
        workflow_copy = json.loads(json.dumps(self.workflow))
        
        # Find the LoadImage node (id: "1") and update its image
        if "1" in workflow_copy:
            workflow_copy["1"]["inputs"]["image"] = image_filename
        
        return workflow_copy
    
    async def process_image_async(self, session: aiohttp.ClientSession,
                                gpu_id: int, image_path: str, original_image_name: str) -> Dict:
        """Process a single image on a specific GPU"""
        server_url = f"http://localhost:{self.base_ports[gpu_id]}"
        
        print(f"Processing {original_image_name} (source: {image_path}) on GPU {gpu_id}")
        
        # Upload image to server using the API
        upload_result = await self.upload_image_async(session, server_url, image_path, original_image_name)
        
        if not upload_result or 'name' not in upload_result:
            return {
                'status': 'failed',
                'gpu_id': gpu_id,
                'image': image_path,
                'original_name': original_image_name,
                'error': f"Failed to upload image '{original_image_name}' via API to {server_url}"
            }
        
        # Modify workflow to use the uploaded image name from API response
        # upload_result['name'] is the filename as ComfyUI sees it (e.g., ComfyUI_00001_.png)
        prompt = self.modify_workflow_for_image(upload_result['name'])
        
        # Queue the prompt
        result = await self.queue_prompt_async(session, server_url, prompt)
        
        if result and 'prompt_id' in result:
            prompt_id = result['prompt_id']
            
            # Wait for completion
            completion_result = await self.wait_for_completion_async(
                session, server_url, prompt_id
            )
            
            if completion_result['status'] == 'completed':
                # Find output images
                outputs = completion_result.get('outputs', {})
                output_images = []
                
                # Look for SaveImage nodes (ids: "20" and "52")
                for node_id in ["20", "52"]:
                    if node_id in outputs and 'images' in outputs[node_id]:
                        output_images.extend(outputs[node_id]['images'])
                
                return {
                    'status': 'completed',
                    'gpu_id': gpu_id,
                    'image': image_path,
                    'original_name': original_image_name,
                    'prompt_id': prompt_id,
                    'output_images': output_images
                }
            else:
                return {
                    'status': completion_result['status'],
                    'gpu_id': gpu_id,
                    'image': image_path,
                    'original_name': original_image_name,
                    'error': completion_result.get('error', 'Unknown error')
                }
        
        return {
            'status': 'failed',
            'gpu_id': gpu_id,
            'image': image_path,
            'original_name': original_image_name,
            'error': f"Failed to queue prompt for {original_image_name} after API upload"
        }
    
    async def process_batch_async(self, image_paths: List[str], 
                                 max_concurrent: int = None) -> List[Dict]:
        """Process a batch of images across all GPUs"""
        if max_concurrent is None:
            max_concurrent = self.num_gpus
        
        # Create a semaphore to limit concurrent tasks
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_with_semaphore(gpu_id: int, image_path: str):
            async with semaphore:
                return await self.process_image_async(session, gpu_id, image_path, os.path.basename(image_path))
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            
            # Distribute images across GPUs
            for i, image_path in enumerate(image_paths):
                gpu_id = i % self.num_gpus
                task = process_with_semaphore(gpu_id, image_path)
                tasks.append(task)
            
            # Wait for all tasks to complete
            results = await asyncio.gather(*tasks)
        
        return results
    
    def process_batch(self, image_paths: List[str]) -> List[Dict]:
        """Synchronous wrapper for batch processing"""
        return asyncio.run(self.process_batch_async(image_paths))
    
    def download_outputs(self, results: List[Dict], output_dir: str = "outputs"):
        """Download output images from completed processes"""
        os.makedirs(output_dir, exist_ok=True)
        
        for result in results:
            if result['status'] == 'completed' and 'output_images' in result:
                gpu_id = result['gpu_id']
                server_url = f"http://localhost:{self.base_ports[gpu_id]}"
                
                for img_info in result['output_images']:
                    filename = img_info['filename']
                    subfolder = img_info.get('subfolder', '')
                    
                    # Download the image
                    if subfolder:
                        url = f"{server_url}/view?filename={filename}&subfolder={subfolder}&type=output"
                    else:
                        url = f"{server_url}/view?filename={filename}&type=output"
                    
                    response = requests.get(url)
                    if response.status_code == 200:
                        output_path = os.path.join(output_dir, filename)
                        with open(output_path, 'wb') as f:
                            f.write(response.content)
                        print(f"Downloaded: {output_path}")

# Usage example
if __name__ == "__main__":
    # Initialize the orchestrator
    orchestrator = ComfyUIMultiGPU(
        workflow_path="workflow.json",  # Your API format workflow
        num_gpus=8,
        comfyui_path="/workspace/ComfyUI",
        base_port=8200  # Starting port
    )
    
    # Start ComfyUI instances
    print("Starting ComfyUI instances...")
    processes = orchestrator.start_comfyui_instances()
    
    # Wait a bit more for all servers to fully initialize
    print("Waiting for servers to initialize...")
    time.sleep(15)
    
    # Prepare list of images to process
    input_dir = "/workspace/ComfyUI/input"  # Adjust to your input directory
    image_paths = []
    
    # Collect all image files
    for ext in ['*.jpg', '*.jpeg', '*.png']:
        image_paths.extend(Path(input_dir).glob(ext))
    
    image_paths = [str(p) for p in image_paths]
    
    if not image_paths:
        print("No images found in input directory!")
        sys.exit(1)
    
    print(f"\nProcessing {len(image_paths)} images across {orchestrator.num_gpus} GPUs")
    
    # Process all images
    results = orchestrator.process_batch(image_paths)
    
    # Print results
    completed = sum(1 for r in results if r['status'] == 'completed')
    failed = sum(1 for r in results if r['status'] != 'completed')
    
    print(f"\nResults:")
    print(f"Completed: {completed}/{len(results)}")
    print(f"Failed: {failed}/{len(results)}")
    
    for result in results:
        status = result['status']
        gpu = result['gpu_id']
        image = os.path.basename(result['image'])
        
        if status == 'completed':
            print(f"✓ {image} - GPU {gpu} - Success")
        else:
            error = result.get('error', 'Unknown error')
            print(f"✗ {image} - GPU {gpu} - {status}: {error}")
    
    # Download output images
    if completed > 0:
        print("\nDownloading output images...")
        orchestrator.download_outputs(results, output_dir="/workspace/ComfyUI/output_multi_gpu")
    
    # Cleanup: terminate all ComfyUI processes
    print("\nShutting down ComfyUI instances...")
    for process in processes:
        process.terminate()
        process.wait()
    
    print("Done!")