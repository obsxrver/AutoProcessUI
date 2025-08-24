#!/bin/bash

source /venv/main/bin/activate
COMFYUI_DIR=${WORKSPACE}/ComfyUI

# Packages are installed after nodes so we can fix them...
# This script provisions ComfyUI with all nodes and models required for:
# - workflow.json (basic workflow)
# - workflow-with-cnet.json (advanced workflow with ControlNet, pose detection, depth maps)

APT_PACKAGES=(
    #"package-1"
    #"package-2"
)

PIP_PACKAGES=(
    "flask>=2.3.0"
    "Flask-SocketIO>=5.3.0"
    "python-socketio>=5.8.0"
    "Werkzeug>=2.3.0"
    "aiohttp>=3.8.0"
    "requests"
    "pandas"
    "websocket-client>=1.6.0"
    "Pillow>=10.0.0"
    "numpy>=1.24.0"
    "httpx==0.23.3"
    "httpcore==0.15.0"
    "instaloader"
    "mediapipe>=0.10.0"  # For pose detection
    "transformers>=4.25.0"  # For various AI models
    "timm>=0.6.12"
    "addict>=2.4.0"
)

NODES=(
    "https://github.com/neverbiasu/ComfyUI-SAM2.git"
    "https://github.com/Acly/comfyui-inpaint-nodes.git"
    "https://github.com/cubiq/ComfyUI_essentials.git"
    "https://github.com/ltdrdata/ComfyUI-Impact-Pack"
    "https://github.com/1038lab/ComfyUI-RMBG"
    "https://github.com/ltdrdata/ComfyUI-Manager"
    "https://github.com/rgthree/rgthree-comfy.git"  # For Image Comparer node
    "https://github.com/Fannovel16/comfyui_controlnet_aux.git"  # For OpenPose and Depth preprocessors
)

WORKFLOWS=(

)

CHECKPOINT_MODELS=(
    "https://civitai.com/api/download/models/1759168"
)

UNET_MODELS=(
)

LORA_MODELS=(
)

VAE_MODELS=(
)

ESRGAN_MODELS=(
)

CONTROLNET_MODELS=(
)

### DO NOT EDIT BELOW HERE UNLESS YOU KNOW WHAT YOU ARE DOING ###

function provisioning_start() {
    provisioning_print_header
    provisioning_get_apt_packages
    
    # Clone and setup BatchProcessUI
    echo "Setting up BatchProcessUI..."
    cd ${WORKSPACE}
    git clone https://github.com/obsxrver/AutoProcessUI.git BatchProcessUI
    cd BatchProcessUI
    
    # Setup supervisor
    echo "Setting up supervisor configuration..."
    mkdir -p /etc/supervisor/conf.d/
    mkdir -p /opt/supervisor-scripts/
    
    # Copy supervisor files
    cp vastai_dropins/batchprocessui.conf /etc/supervisor/conf.d/
    cp vastai_dropins/batchprocessui.sh /opt/supervisor-scripts/
    chmod +x /opt/supervisor-scripts/batchprocessui.sh
    
    # Setup ComfyUI and dependencies
    cd ${WORKSPACE}
    if [ ! -d "ComfyUI" ]; then
        git clone https://github.com/comfyanonymous/ComfyUI.git
        cd ComfyUI
        pip install -r requirements.txt
    fi
    
    # Install custom nodes
    cd ${COMFYUI_DIR}/custom_nodes
    for repo in "${NODES[@]}"; do
        dir="${repo##*/}"
        dir="${dir%.git}"
        if [ ! -d "$dir" ]; then
            git clone "$repo"
            if [ -f "$dir/requirements.txt" ]; then
                pip install -r "$dir/requirements.txt"
            fi
        fi
    done
    
    # Download models
    cd ${COMFYUI_DIR}/models
    
    # SAM2 models
    # meh the node allegedly handles this for us. lets skip downlaoding so as to not get wrong ones
    
    # Inpaint models
    cd ${COMFYUI_DIR}/models
    mkdir -p inpaint
    cd inpaint
    if [ ! -f "fooocus_inpaint_head.pth" ]; then
        wget -c https://huggingface.co/lllyasviel/fooocus_inpaint/resolve/main/fooocus_inpaint_head.pth
        wget -c https://huggingface.co/lllyasviel/fooocus_inpaint/resolve/main/inpaint_v25.fooocus.patch
        wget -c https://huggingface.co/lllyasviel/fooocus_inpaint/resolve/main/inpaint_v26.fooocus.patch
    fi
    
    # Main checkpoint
    cd ${COMFYUI_DIR}/models/checkpoints
    if [ ! -f "juggernaut-ragnarok.safetensors" ]; then
        wget -c https://civitai.com/api/download/models/1759168 -O juggernaut-ragnarok.safetensors
    fi
    # Install pip packages
    provisioning_get_pip_packages
    
    # Reload supervisor
    supervisorctl reread
    supervisorctl update
    
    # Start BatchProcessUI
    supervisorctl start batchprocessui
    
    provisioning_print_end
}

function provisioning_get_apt_packages() {
    if [[ -n $APT_PACKAGES ]]; then
            $APT_INSTALL ${APT_PACKAGES[@]}
    fi
}

function provisioning_get_pip_packages() {
    if [[ -n $PIP_PACKAGES ]]; then
            pip install --no-cache-dir ${PIP_PACKAGES[@]}
    fi
}

function provisioning_print_header() {
    printf "\n##############################################\n#                                            #\n#          Provisioning container            #\n#                                            #\n#         This will take some time           #\n#                                            #\n# Your container will be ready on completion #\n#                                            #\n##############################################\n\n"
}

function provisioning_print_end() {
    printf "\nProvisioning complete:  Application will start now\n\n"
}

function provisioning_has_valid_hf_token() {
    [[ -n "$HF_TOKEN" ]] || return 1
    url="https://huggingface.co/api/whoami-v2"

    response=$(curl -o /dev/null -s -w "%{http_code}" -X GET "$url" \
        -H "Authorization: Bearer $HF_TOKEN" \
        -H "Content-Type: application/json")

    # Check if the token is valid
    if [ "$response" -eq 200 ]; then
        return 0
    else
        return 1
    fi
}

function provisioning_has_valid_civitai_token() {
    [[ -n "$CIVITAI_TOKEN" ]] || return 1
    url="https://civitai.com/api/v1/models?hidden=1&limit=1"

    response=$(curl -o /dev/null -s -w "%{http_code}" -X GET "$url" \
        -H "Authorization: Bearer $CIVITAI_TOKEN" \
        -H "Content-Type: application/json")

    # Check if the token is valid
    if [ "$response" -eq 200 ]; then
        return 0
    else
        return 1
    fi
}

# Download from $1 URL to $2 file path
function provisioning_download() {
    if [[ -n $HF_TOKEN && $1 =~ ^https://([a-zA-Z0-9_-]+\.)?huggingface\.co(/|$|\?) ]]; then
        auth_token="$HF_TOKEN"
    elif 
        [[ -n $CIVITAI_TOKEN && $1 =~ ^https://([a-zA-Z0-9_-]+\.)?civitai\.com(/|$|\?) ]]; then
        auth_token="$CIVITAI_TOKEN"
    fi
    if [[ -n $auth_token ]];then
        wget --header="Authorization: Bearer $auth_token" -qnc --content-disposition --show-progress -e dotbytes="${3:-4M}" -P "$2" "$1"
    else
        wget -qnc --content-disposition --show-progress -e dotbytes="${3:-4M}" -P "$2" "$1"
    fi
}

# Allow user to disable provisioning if they started with a script they didn't want
if [[ ! -f /.noprovisioning ]]; then
    provisioning_start
fi
