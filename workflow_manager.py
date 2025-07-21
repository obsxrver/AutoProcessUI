#!/usr/bin/env python
"""Workflow Manager for ComfyUI with title-based node references"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

class WorkflowManager:
    def __init__(self, workflow_directory: str = "."):
        self.workflow_directory = Path(workflow_directory)
        self.workflows = {}
        self.current_workflow = None
        self.current_workflow_data = None
        self.node_mappings = {}
        
        # Required node titles for the application
        self.required_nodes = {
            'input_image': 'INPUT_IMAGE',
            'positive_prompt': 'POSITIVE',
            'negative_prompt': 'NEGATIVE', 
            'checkpoint_loader': 'Load Checkpoint',
            'main_sampler': 'KSampler (Advanced)',
            'output': 'OUTPUT',
            'output_refined': 'OUTPUT_REFINED',
            'refiner': 'Detailer (SEGS)',
            'vae_decode': 'VAE Decode'
        }
        
        self.load_available_workflows()
    
    def load_available_workflows(self):
        """Scan for available workflow files"""
        workflow_files = list(self.workflow_directory.glob("workflow*.json"))
        
        for workflow_file in workflow_files:
            try:
                with open(workflow_file, 'r') as f:
                    workflow_data = json.load(f)
                
                # Extract display name from filename
                display_name = workflow_file.stem.replace('workflow', '').replace('-', ' ').strip()
                if not display_name:
                    display_name = "Default"
                else:
                    display_name = display_name.replace('_', ' ').title()
                
                self.workflows[workflow_file.stem] = {
                    'name': display_name,
                    'file': workflow_file,
                    'data': workflow_data
                }
                
                print(f"Loaded workflow: {display_name} ({workflow_file.name})")
                
            except Exception as e:
                print(f"Error loading workflow {workflow_file}: {e}")
        
        # Set default workflow
        if 'workflow' in self.workflows:
            self.set_current_workflow('workflow')
        elif self.workflows:
            self.set_current_workflow(list(self.workflows.keys())[0])
    
    def get_available_workflows(self) -> Dict[str, str]:
        """Get list of available workflows"""
        return {key: info['name'] for key, info in self.workflows.items()}
    
    def set_current_workflow(self, workflow_key: str) -> bool:
        """Set the current active workflow"""
        if workflow_key not in self.workflows:
            return False
        
        self.current_workflow = workflow_key
        self.current_workflow_data = self.workflows[workflow_key]['data']
        self.node_mappings = self._build_node_mappings()
        
        print(f"Switched to workflow: {self.workflows[workflow_key]['name']}")
        return True
    
    def _build_node_mappings(self) -> Dict[str, str]:
        """Build mappings from required node types to actual node IDs"""
        mappings = {}
        
        if not self.current_workflow_data:
            return mappings
        
        # Find nodes by their titles
        for node_id, node_data in self.current_workflow_data.items():
            if not isinstance(node_data, dict) or '_meta' not in node_data:
                continue
            
            title = node_data['_meta'].get('title', '')
            
            # Map required nodes
            for req_key, req_title in self.required_nodes.items():
                if title == req_title:
                    if req_key in ['positive_prompt', 'negative_prompt']:
                        # Handle multiple CLIP Text Encode nodes
                        if req_key not in mappings:
                            mappings[req_key] = []
                        mappings[req_key].append(node_id)
                    else:
                        mappings[req_key] = node_id
                    break
        
        # For prompt nodes, we need to differentiate positive and negative
        if 'positive_prompt' in mappings and isinstance(mappings['positive_prompt'], list):
            # Sort by node ID and assign first to positive, others based on content
            prompt_nodes = mappings['positive_prompt']
            positive_node = None
            negative_node = None
            
            for node_id in prompt_nodes:
                node_data = self.current_workflow_data[node_id]
                text_content = node_data.get('inputs', {}).get('text', '')
                
                # Heuristic: negative prompts usually contain negative words
                negative_words = ['blurry', 'low quality', 'worst quality', 'bad', 'ugly', 'deformed']
                is_negative = any(word in text_content.lower() for word in negative_words)
                
                if is_negative and negative_node is None:
                    negative_node = node_id
                elif not is_negative and positive_node is None:
                    positive_node = node_id
            
            # Fallback: use order if heuristic fails
            if positive_node is None:
                positive_node = prompt_nodes[0]
            if negative_node is None and len(prompt_nodes) > 1:
                negative_node = prompt_nodes[1] if prompt_nodes[1] != positive_node else prompt_nodes[0]
            
            mappings['positive_prompt'] = positive_node
            mappings['negative_prompt'] = negative_node
        
        # Print mappings for debugging
        print(f"Node mappings for {self.current_workflow}:")
        for key, node_id in mappings.items():
            print(f"  {key}: {node_id}")
        
        return mappings
    
    def get_node_id(self, node_type: str) -> Optional[str]:
        """Get the actual node ID for a required node type"""
        return self.node_mappings.get(node_type)
    
    def get_current_workflow_copy(self) -> Dict[str, Any]:
        """Get a deep copy of the current workflow"""
        if not self.current_workflow_data:
            raise ValueError("No workflow loaded")
        
        return json.loads(json.dumps(self.current_workflow_data))
    
    def modify_workflow_for_image(self, image_filename: str) -> Dict[str, Any]:
        """Modify workflow to use a specific image"""
        workflow_copy = self.get_current_workflow_copy()
        
        # Update input image node
        input_node_id = self.get_node_id('input_image')
        if input_node_id and input_node_id in workflow_copy:
            workflow_copy[input_node_id]["inputs"]["image"] = image_filename
        else:
            print(f"Warning: Could not find input image node with title 'INPUT_IMAGE'")
        
        return workflow_copy
    
    def update_prompts(self, workflow: Dict[str, Any], positive_prompt: str, negative_prompt: str):
        """Update prompt nodes in workflow"""
        # Update positive prompt
        pos_node_id = self.get_node_id('positive_prompt')
        if pos_node_id and pos_node_id in workflow:
            workflow[pos_node_id]["inputs"]["text"] = positive_prompt
        
        # Update negative prompt  
        neg_node_id = self.get_node_id('negative_prompt')
        if neg_node_id and neg_node_id in workflow:
            workflow[neg_node_id]["inputs"]["text"] = negative_prompt
    
    def update_model_settings(self, workflow: Dict[str, Any], model_name: str):
        """Update model selection in workflow"""
        checkpoint_node_id = self.get_node_id('checkpoint_loader')
        if checkpoint_node_id and checkpoint_node_id in workflow:
            workflow[checkpoint_node_id]["inputs"]["ckpt_name"] = model_name
    
    def update_sampler_settings(self, workflow: Dict[str, Any], settings: Dict[str, Any]):
        """Update main sampler settings"""
        sampler_node_id = self.get_node_id('main_sampler')
        if sampler_node_id and sampler_node_id in workflow:
            node_inputs = workflow[sampler_node_id]["inputs"]
            
            if 'main_steps' in settings:
                node_inputs["steps"] = settings['main_steps']
            if 'main_cfg' in settings:
                node_inputs["cfg"] = settings['main_cfg']
            if 'main_sampler' in settings:
                node_inputs["sampler_name"] = settings['main_sampler']
            if 'main_scheduler' in settings:
                node_inputs["scheduler"] = settings['main_scheduler']
    
    def update_refiner_settings(self, workflow: Dict[str, Any], settings: Dict[str, Any]):
        """Update refiner/detailer settings"""
        refiner_node_id = self.get_node_id('refiner')
        if refiner_node_id and refiner_node_id in workflow:
            node_inputs = workflow[refiner_node_id]["inputs"]
            
            if 'refiner_steps' in settings:
                node_inputs["steps"] = settings['refiner_steps']
            if 'refiner_cfg' in settings:
                node_inputs["cfg"] = settings['refiner_cfg']
            if 'refiner_sampler' in settings:
                node_inputs["sampler_name"] = settings['refiner_sampler']
            if 'refiner_scheduler' in settings:
                node_inputs["scheduler"] = settings['refiner_scheduler']
            if 'refiner_denoise' in settings:
                node_inputs["denoise"] = settings['refiner_denoise']
            if 'refiner_cycles' in settings:
                node_inputs["cycle"] = settings['refiner_cycles']
    
    def get_output_node_ids(self) -> Dict[str, str]:
        """Get output node IDs for result processing"""
        return {
            'output': self.get_node_id('output'),
            'output_refined': self.get_node_id('output_refined')
        }
    
    def get_default_prompts(self) -> Dict[str, str]:
        """Extract default prompts from current workflow"""
        prompts = {'positive': '', 'negative': ''}
        
        pos_node_id = self.get_node_id('positive_prompt')
        if pos_node_id and pos_node_id in self.current_workflow_data:
            prompts['positive'] = self.current_workflow_data[pos_node_id]["inputs"].get("text", "")
        
        neg_node_id = self.get_node_id('negative_prompt')
        if neg_node_id and neg_node_id in self.current_workflow_data:
            prompts['negative'] = self.current_workflow_data[neg_node_id]["inputs"].get("text", "")
        
        return prompts 