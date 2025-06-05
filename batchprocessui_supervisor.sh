#!/bin/bash

# Set process name for logging
export PROC_NAME="batchprocessui"

# User can configure startup by removing the reference in /etc.portal.yaml - So wait for that file and check it
while [ ! -f "$(realpath -q /etc/portal.yaml 2>/dev/null)" ]; do
    echo "Waiting for /etc/portal.yaml before starting ${PROC_NAME}..." | tee -a "/var/log/portal/${PROC_NAME}.log"
    sleep 1
done

# Check for batchprocessui in the portal config
search_term="batchprocessui"
search_pattern=$(echo "$search_term" | sed 's/[ _-]/[ _-]/g')
if ! grep -qiE "^[^#].*${search_pattern}" /etc/portal.yaml; then
    echo "Skipping startup for ${PROC_NAME} (not in /etc/portal.yaml)" | tee -a "/var/log/portal/${PROC_NAME}.log"
    exit 0
fi

# Activate the venv
. /venv/main/bin/activate

# Wait for provisioning to complete
while [ -f "/.provisioning" ]; do
    echo "$PROC_NAME startup paused until instance provisioning has completed (/.provisioning present)" | tee -a "/var/log/portal/${PROC_NAME}.log"
    sleep 10
done

# Set environment variables
export COMFYUI_PATH=${WORKSPACE}/ComfyUI
export CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7  # Adjust based on available GPUs
export GRADIO_PORT=7860  # Internal port for Gradio app

# Avoid git errors because we run as root but files are owned by 'user'
export GIT_CONFIG_GLOBAL=/tmp/temporary-git-config
git config --file $GIT_CONFIG_GLOBAL --add safe.directory '*'

# Ensure output directories exist
mkdir -p ${WORKSPACE}/BatchProcessUI/gradio_outputs
mkdir -p ${WORKSPACE}/BatchProcessUI/temp_inputs
mkdir -p /var/log/portal

# Install/update dependencies if needed
cd ${WORKSPACE}/BatchProcessUI
if [ -f "requirements.txt" ]; then
    echo "Installing/updating dependencies..." | tee -a "/var/log/portal/${PROC_NAME}.log"
    pip install -r requirements.txt --upgrade 2>&1 | tee -a "/var/log/portal/${PROC_NAME}.log"
    
    # Verify Gradio version
    echo "Checking Gradio version..." | tee -a "/var/log/portal/${PROC_NAME}.log"
    python -c "import gradio; print(f'Gradio version: {gradio.__version__}')" 2>&1 | tee -a "/var/log/portal/${PROC_NAME}.log"
fi

# Kill any existing ComfyUI instances on our batch processing ports
for port in {8200..8207}; do
    fuser -k ${port}/tcp 2>/dev/null || true
done

# Check Python version
echo "Python version:" | tee -a "/var/log/portal/${PROC_NAME}.log"
python --version 2>&1 | tee -a "/var/log/portal/${PROC_NAME}.log"

# Launch BatchProcessUI
echo "Starting BatchProcessUI on port 7860..." | tee -a "/var/log/portal/${PROC_NAME}.log"
cd ${WORKSPACE}/BatchProcessUI

# First run the test script if it exists
if [ -f "test_startup.py" ]; then
    echo "Running environment test..." | tee -a "/var/log/portal/${PROC_NAME}.log"
    python test_startup.py 2>&1 | tee -a "/var/log/portal/${PROC_NAME}.log"
fi

# Use the startup wrapper if it exists, otherwise fall back to direct launch
if [ -f "start_app.py" ]; then
    echo "Using startup wrapper..." | tee -a "/var/log/portal/${PROC_NAME}.log"
    exec python start_app.py 2>&1 | tee -a "/var/log/portal/${PROC_NAME}.log"
else
    echo "Using direct launch..." | tee -a "/var/log/portal/${PROC_NAME}.log"
    exec python gradio_app.py 2>&1 | tee -a "/var/log/portal/${PROC_NAME}.log"
fi 