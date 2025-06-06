#!/bin/bash

# Default values
PORT=18384
VASTAI=false
COMFYUI_PATH=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --port)
            PORT="$2"
            shift 2
            ;;
        --vastai)
            VASTAI=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--port PORT] [--vastai]"
            exit 1
            ;;
    esac
done

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to install Python packages
install_requirements() {
    echo "Installing Python requirements..."
    pip install -r requirements.txt
}

# Function to set up VastAI configuration
setup_vastai() {
    echo "Setting up VastAI configuration..."
    
    # Create supervisor config directory if it doesn't exist
    sudo mkdir -p /etc/supervisor/conf.d/
    
    # Handle existing syncthing configuration
    if [ -f "/etc/supervisor/conf.d/syncthing.conf" ]; then
        echo "Found existing syncthing.conf, moving it to syncthing.conf.old..."
        sudo mv /etc/supervisor/conf.d/syncthing.conf /etc/supervisor/conf.d/syncthing.conf.old
    fi
    
    # Copy supervisor configuration
    sudo cp vastai_dropins/batchprocessui.conf /etc/supervisor/conf.d/
    
    # Create supervisor scripts directory
    sudo mkdir -p /opt/supervisor-scripts/
    
    # Copy and make executable the startup script
    sudo cp vastai_dropins/batchprocessui.sh /opt/supervisor-scripts/
    sudo chmod +x /opt/supervisor-scripts/batchprocessui.sh
    
    # Update portal.yaml
    echo "Updating /etc/portal.yaml..."
    if [ ! -f "/etc/portal.yaml" ]; then
        sudo touch /etc/portal.yaml
    fi
    
    # Add BatchProcessUI configuration
    echo "
  BatchProcessUI:
    hostname: localhost
    external_port: 8384
    internal_port: $PORT
    open_path: /
    name: BatchProcessUI" | sudo tee -a /etc/portal.yaml
    
    echo "VastAI configuration completed."
}

# Function to install and set up ComfyUI
setup_comfyui() {
    echo "Setting up ComfyUI..."
    git clone https://github.com/comfyanonymous/ComfyUI.git
    cd ComfyUI
    pip install -r requirements.txt
    cd ..
    export COMFYUI_PATH="$(pwd)/ComfyUI"
}

# Main setup process
echo "ComfyUI Multi-GPU Batch Processor Setup"
echo "======================================="

# Check Python installation
if ! command_exists python; then
    echo "Error: Python is not installed. Please install Python 3.8 or higher."
    exit 1
fi

# Check pip installation
if ! command_exists pip; then
    echo "Error: pip is not installed. Please install pip."
    exit 1
fi

# Check git installation
if ! command_exists git; then
    echo "Error: git is not installed. Please install git."
    exit 1
fi

# Prompt for ComfyUI path
echo -n "Enter path to existing ComfyUI installation (or press Enter to install new): "
read -r user_comfyui_path

if [ -z "$user_comfyui_path" ]; then
    echo "No path provided. Installing ComfyUI..."
    setup_comfyui
else
    if [ -d "$user_comfyui_path" ]; then
        export COMFYUI_PATH="$user_comfyui_path"
        echo "Using existing ComfyUI installation at $COMFYUI_PATH"
    else
        echo "Error: Directory $user_comfyui_path does not exist."
        exit 1
    fi
fi

# Navigate to ComfyUI custom nodes directory
cd "$COMFYUI_PATH/custom_nodes" || exit 1

# Install ComfyUI-SAM2
echo "Installing ComfyUI-SAM2..."
if [ ! -d "ComfyUI-SAM2" ]; then
    git clone https://github.com/neverbiasu/ComfyUI-SAM2.git
    cd ComfyUI-SAM2
    pip install -r requirements.txt
    cd ..
fi

# Install ComfyUI-Inpaint-Nodes
echo "Installing ComfyUI-Inpaint-Nodes..."
if [ ! -d "comfyui-inpaint-nodes" ]; then
    git clone https://github.com/Acly/comfyui-inpaint-nodes.git
    cd comfyui-inpaint-nodes
    pip install -r requirements.txt
    cd ..
fi

# Install ComfyUI_essentials
echo "Installing ComfyUI_essentials..."
if [ ! -d "ComfyUI_essentials" ]; then
    git clone https://github.com/cubiq/ComfyUI_essentials.git
    cd ComfyUI_essentials
    pip install -r requirements.txt
    cd ..
fi

# Install ComfyUI-Impact-Pack
echo "Installing ComfyUI-Impact-Pack..."
if [ ! -d "ComfyUI-Impact-Pack" ]; then
    git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git
    cd ComfyUI-Impact-Pack
    python install.py
    cd ..
fi

# Install RMBG node
echo "Installing RMBG node..."
if [ ! -d "ComfyUI-RMBG" ]; then
    git clone https://github.com/Jcd1230/rembg-comfyui-node.git ComfyUI-RMBG
    cd ComfyUI-RMBG
    pip install rembg
    cd ..
fi

# Download required models
echo "Downloading required models..."
cd "$COMFYUI_PATH/models" || exit 1

# SAM2 models
mkdir -p sam2
cd sam2 || exit 1
if [ ! -f "sam2_1_hiera_large.pt" ]; then
    echo "Downloading SAM2 model..."
    wget -c https://huggingface.co/Kijai/sam2-safetensors/resolve/main/sam2_hiera_large.safetensors -O sam2_1_hiera_large.pt
fi

# GroundingDINO models
cd "$COMFYUI_PATH/models" || exit 1
mkdir -p grounding-dino
cd grounding-dino || exit 1
if [ ! -f "GroundingDINO_SwinB.pth" ]; then
    echo "Downloading GroundingDINO models..."
    wget -c https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/groundingdino_swinb_cogcoor.pth -O GroundingDINO_SwinB.pth
    wget -c https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/groundingdino_swint_ogc.pth -O GroundingDINO_SwinT_OGC.pth
fi

# Inpaint models
cd "$COMFYUI_PATH/models" || exit 1
mkdir -p inpaint
cd inpaint || exit 1
if [ ! -f "fooocus_inpaint_head.pth" ]; then
    echo "Downloading Fooocus inpaint models..."
    wget -c https://huggingface.co/lllyasviel/fooocus_inpaint/resolve/main/fooocus_inpaint_head.pth
    wget -c https://huggingface.co/lllyasviel/fooocus_inpaint/resolve/main/inpaint_v25.fooocus.patch
    wget -c https://huggingface.co/lllyasviel/fooocus_inpaint/resolve/main/inpaint_v26.fooocus.patch
fi

# Main checkpoint
cd "$COMFYUI_PATH/models/checkpoints" || exit 1
if [ ! -f "juggernaut-ragnarok.safetensors" ]; then
    echo "Downloading Juggernaut checkpoint..."
    wget -c https://civitai.com/api/download/models/1759168 -O juggernaut-ragnarok.safetensors
fi

# Return to original directory and install requirements
cd - || exit 1
install_requirements

# Set up VastAI if requested
if [ "$VASTAI" = true ]; then
    setup_vastai
fi

echo "Setup completed successfully!"
echo "To start the application, run:"
echo "python app.py --port $PORT"

