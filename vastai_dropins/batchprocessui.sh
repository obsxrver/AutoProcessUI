#!/bin/bash
#/opt/supervisor-scripts/batchprocessui.sh
# User can configure startup by removing the reference in /etc.portal.yaml - So wait for that file and check it
while [ ! -f "$(realpath -q /etc/portal.yaml 2>/dev/null)" ]; do
    echo "Waiting for /etc/portal.yaml before starting ${PROC_NAME}..." | tee -a "/var/log/portal/${PROC_NAME}.log"
    sleep 1
done

# Check for comfyui in the portal config
search_term="batchprocessui"
search_pattern=$(echo "$search_term" | sed 's/[ _-]/[ _-]/g')
if ! grep -qiE "^[^#].*${search_pattern}" /etc/portal.yaml; then
    echo "Skipping startup for ${PROC_NAME} (not in /etc/portal.yaml)" | tee -a "/var/log/portal/${PROC_NAME}.log"
    exit 0
fi

# Get port from portal.yaml
INTERNAL_PORT=$(grep -A4 "BatchProcessUI:" /etc/portal.yaml | grep "internal_port:" | awk '{print $2}')
if [ -z "$INTERNAL_PORT" ]; then
    INTERNAL_PORT=18384  # Default port if not found
fi

# Activate the venv
. /venv/main/bin/activate

# Wait for provisioning to complete
while [ -f "/.provisioning" ]; do
    echo "$PROC_NAME startup paused until instance provisioning has completed (/.provisioning present)"
    sleep 10
done

export COMFYUI_PATH=${WORKSPACE}/ComfyUI
# Avoid git errors because we run as root but files are owned by 'user'
export GIT_CONFIG_GLOBAL=/tmp/temporary-git-config
git config --file $GIT_CONFIG_GLOBAL --add safe.directory '*'

# Launch ComfyUI
cd ${WORKSPACE}/BatchProcessUI
LD_PRELOAD=libtcmalloc_minimal.so.4 \
        python app.py --port $INTERNAL_PORT 2>&1 | tee -a "/var/log/portal/${PROC_NAME}.log"
