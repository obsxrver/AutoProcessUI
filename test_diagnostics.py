#!/usr/bin/env python
"""Diagnostic script to test ComfyUI server connections and functionality"""

import os
import sys
import json
import time
import requests
import asyncio
import aiohttp
from pathlib import Path

def check_comfyui_servers(base_port=8200, num_gpus=8):
    """Check if ComfyUI servers are running"""
    print("Checking ComfyUI servers...")
    servers_status = {}
    
    for i in range(num_gpus):
        port = base_port + i
        server_url = f"http://localhost:{port}"
        
        try:
            response = requests.get(f"{server_url}/system_stats", timeout=5)
            if response.status_code == 200:
                stats = response.json()
                servers_status[i] = {
                    'status': 'running',
                    'port': port,
                    'stats': stats
                }
                print(f"✓ GPU {i} (port {port}): Running")
            else:
                servers_status[i] = {
                    'status': 'error',
                    'port': port,
                    'error': f'HTTP {response.status_code}'
                }
                print(f"✗ GPU {i} (port {port}): Error - HTTP {response.status_code}")
        except Exception as e:
            servers_status[i] = {
                'status': 'offline',
                'port': port,
                'error': str(e)
            }
            print(f"✗ GPU {i} (port {port}): Offline - {e}")
    
    return servers_status

async def test_image_upload(server_url, test_image_path):
    """Test image upload to a specific server"""
    print(f"\nTesting upload to {server_url}...")
    
    if not os.path.exists(test_image_path):
        print(f"Error: Test image not found at {test_image_path}")
        return False
    
    async with aiohttp.ClientSession() as session:
        try:
            # Create form data
            form_data = aiohttp.FormData()
            
            with open(test_image_path, 'rb') as f:
                form_data.add_field(
                    'image',
                    f,
                    filename=os.path.basename(test_image_path),
                    content_type='image/png'
                )
                
                # Upload
                upload_url = f"{server_url}/upload/image"
                async with session.post(upload_url, data=form_data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        print(f"✓ Upload successful: {result}")
                        return True
                    else:
                        error_text = await resp.text()
                        print(f"✗ Upload failed: HTTP {resp.status} - {error_text}")
                        return False
                        
        except Exception as e:
            print(f"✗ Upload error: {e}")
            import traceback
            traceback.print_exc()
            return False

def check_workflow_file():
    """Check if workflow.json exists and is valid"""
    print("\nChecking workflow.json...")
    
    if not os.path.exists("workflow.json"):
        print("✗ workflow.json not found!")
        return False
    
    try:
        with open("workflow.json", 'r') as f:
            workflow = json.load(f)
        
        # Check for required nodes
        required_nodes = ["1", "10", "15", "20", "52"]
        missing_nodes = [node for node in required_nodes if node not in workflow]
        
        if missing_nodes:
            print(f"✗ Missing required nodes in workflow: {missing_nodes}")
            return False
        
        print("✓ workflow.json is valid")
        return True
        
    except json.JSONDecodeError as e:
        print(f"✗ workflow.json is not valid JSON: {e}")
        return False
    except Exception as e:
        print(f"✗ Error reading workflow.json: {e}")
        return False

def check_directories():
    """Check if required directories exist"""
    print("\nChecking directories...")
    
    dirs_to_check = {
        'temp_inputs': 'Upload directory',
        'gradio_outputs': 'Output directory',
        'static': 'Static files directory',
        'templates': 'Templates directory'
    }
    
    all_good = True
    for dir_name, description in dirs_to_check.items():
        if os.path.exists(dir_name):
            print(f"✓ {description} ({dir_name}) exists")
        else:
            print(f"✗ {description} ({dir_name}) missing - creating...")
            try:
                os.makedirs(dir_name, exist_ok=True)
                print(f"  Created {dir_name}")
            except Exception as e:
                print(f"  Failed to create {dir_name}: {e}")
                all_good = False
    
    return all_good

def create_test_image():
    """Create a simple test image"""
    try:
        from PIL import Image
        
        # Create a simple 512x512 test image
        img = Image.new('RGB', (512, 512), color='red')
        test_path = 'test_image.png'
        img.save(test_path)
        print(f"✓ Created test image: {test_path}")
        return test_path
    except ImportError:
        print("✗ PIL not installed, cannot create test image")
        return None
    except Exception as e:
        print(f"✗ Failed to create test image: {e}")
        return None

async def main():
    """Run all diagnostics"""
    print("ComfyUI Batch Processor Diagnostics")
    print("=" * 50)
    
    # Check directories
    check_directories()
    
    # Check workflow
    workflow_ok = check_workflow_file()
    
    # Check servers
    servers = check_comfyui_servers()
    running_servers = [s for s in servers.values() if s['status'] == 'running']
    
    if not running_servers:
        print("\n⚠️  No ComfyUI servers are running!")
        print("Please start ComfyUI servers first.")
        return
    
    print(f"\nFound {len(running_servers)} running server(s)")
    
    # Create test image
    test_image = create_test_image()
    if not test_image:
        # Try to find an existing image
        for ext in ['*.png', '*.jpg', '*.jpeg']:
            images = list(Path('.').glob(ext))
            if images:
                test_image = str(images[0])
                print(f"Using existing image: {test_image}")
                break
    
    if test_image and running_servers:
        # Test upload on first running server
        first_server = running_servers[0]
        server_url = f"http://localhost:{first_server['port']}"
        await test_image_upload(server_url, test_image)
    
    # Summary
    print("\n" + "=" * 50)
    print("Summary:")
    print(f"- Directories: {'✓ OK' if check_directories() else '✗ Issues found'}")
    print(f"- Workflow: {'✓ OK' if workflow_ok else '✗ Issues found'}")
    print(f"- Servers: {len(running_servers)}/{len(servers)} running")
    
    if len(running_servers) < len(servers):
        print("\n⚠️  Some servers are not running. This may cause processing failures.")
        print("Consider starting all ComfyUI instances or reducing the number of GPUs in the configuration.")

if __name__ == "__main__":
    asyncio.run(main()) 