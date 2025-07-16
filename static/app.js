// ComfyUI Batch Processor JavaScript

class ComfyUIApp {
    constructor() {
        this.socket = null;
        this.processingCount = 0;
        this.totalCount = 0;
        this.isProcessing = false;
        
        // Pagination state
        this.currentPage = 1;
        this.itemsPerPage = 24;
        this.allResults = [];
        this.filteredResults = [];
        this.showUnrefined = true;
        
        // Preview management - track per GPU server
        this.previewsEnabled = true;
        this.pendingPreviewsByGpu = new Map(); // Track pending requests per GPU
        this.maxPendingPerGpu = 2; // Maximum pending previews per GPU server
        this.imageGpuMapping = new Map(); // Track which GPU each image is being processed on
        this.droppedPreviews = 0; // Track dropped preview count for UI feedback
        
        this.init();
    }

    init() {
        this.loadUserPreferences();
        this.setupSocketIO();
        this.setupEventListeners();
        this.setupDragAndDrop();
        this.setupKeyboardShortcuts();
        this.startStatusPolling();
        this.loadAvailableModels();
    }

    loadUserPreferences() {
        // Load preview preferences from localStorage
        const previewsEnabled = localStorage.getItem('previewsEnabled');
        if (previewsEnabled !== null) {
            this.previewsEnabled = previewsEnabled === 'true';
        }
        
        // Initialize toggle state
        const toggle = document.getElementById('previewsToggle');
        if (toggle) {
            toggle.checked = this.previewsEnabled;
        }
        
        // Initialize preview gallery state
        if (!this.previewsEnabled) {
            setTimeout(() => {
                const previewGallery = document.getElementById('livePreview');
                if (previewGallery) {
                    previewGallery.innerHTML = '<div class="empty-state"><i class="fas fa-eye-slash"></i><p>Live previews disabled</p></div>';
                }
            }, 100);
        }
    }

    saveUserPreferences() {
        localStorage.setItem('previewsEnabled', this.previewsEnabled.toString());
    }

    shouldThrottlePreview(gpuId) {
        if (!this.previewsEnabled) {
            return true;
        }
        
        // Check if this specific GPU has reached its limit
        const pendingForGpu = this.pendingPreviewsByGpu.get(gpuId) || 0;
        return pendingForGpu >= this.maxPendingPerGpu;
    }

    getAvailableGpu() {
        // Find a GPU with available preview slots
        for (let gpu = 0; gpu < 8; gpu++) { // Assuming max 8 GPUs
            const pending = this.pendingPreviewsByGpu.get(gpu) || 0;
            if (pending < this.maxPendingPerGpu) {
                return gpu;
            }
        }
        return null; // No available GPU slots
    }

    queuePreviewRequest(requestData) {
        if (!this.previewsEnabled) {
            return;
        }
        
        // Get GPU ID from image mapping or find available GPU
        let gpuId = requestData.gpu_id;
        if (gpuId === undefined && requestData.image_id) {
            gpuId = this.imageGpuMapping.get(requestData.image_id);
        }
        if (gpuId === undefined) {
            gpuId = this.getAvailableGpu();
        }
        
        if (gpuId === null || this.shouldThrottlePreview(gpuId)) {
            // Drop the preview request instead of queuing
            this.droppedPreviews++;
            this.updatePreviewQueueStatus();
            return;
        }
        
        this.executePreviewRequest({...requestData, gpu_id: gpuId});
    }

    executePreviewRequest(requestData) {
        const gpuId = requestData.gpu_id || 0;
        const requestId = `${requestData.image_id}_${gpuId}_${Date.now()}`;
        
        // Increment pending count for this GPU
        const currentPending = this.pendingPreviewsByGpu.get(gpuId) || 0;
        this.pendingPreviewsByGpu.set(gpuId, currentPending + 1);
        this.updatePreviewQueueStatus();
        
        // Create new image element for loading
        const newImg = document.createElement('img');
        newImg.dataset.requestId = requestId;
        newImg.dataset.gpuId = gpuId;
        
        const cleanup = () => {
            // Decrement pending count for this GPU
            const pending = this.pendingPreviewsByGpu.get(gpuId) || 1;
            this.pendingPreviewsByGpu.set(gpuId, Math.max(0, pending - 1));
            this.updatePreviewQueueStatus();
        };
        
        newImg.onload = () => {
            this.handlePreviewImageLoaded(requestData, newImg);
            cleanup();
        };
        
        newImg.onerror = () => {
            console.warn('Failed to load preview image for', requestData.image_id, 'on GPU', gpuId);
            cleanup();
        };
        
        // Set timeout (simplified without network detection)
        setTimeout(() => {
            if (newImg.parentNode) {
                console.warn('Preview request timed out for', requestData.image_id, 'on GPU', gpuId);
                cleanup();
            }
        }, 8000);
        
        // Start loading
        if (requestData.preview_path) {
            newImg.src = requestData.preview_path;
        } else if (requestData.preview_url) {
            newImg.src = requestData.preview_url;
        }
    }

    updatePreviewQueueStatus() {
        const previewGallery = document.getElementById('livePreview');
        if (!previewGallery) return;
        
        // Calculate total pending across all GPUs
        let totalPending = 0;
        for (const count of this.pendingPreviewsByGpu.values()) {
            totalPending += count;
        }
        
        // Remove all status indicators
        previewGallery.classList.remove('preview-status');
        const statusIndicator = previewGallery.querySelector('.preview-status-indicator');
        if (statusIndicator) {
            statusIndicator.remove();
        }
    }

    handlePreviewImageLoaded(requestData, imgElement) {
        const previewGallery = document.getElementById('livePreview');
        if (!previewGallery) return;

        // Find or create preview item container
        let previewItem = previewGallery.querySelector(`[data-preview-id="${requestData.image_id}"]`);
        
        if (!previewItem) {
            previewItem = document.createElement('div');
            previewItem.className = 'image-item preview-container fade-in-up';
            previewItem.dataset.previewId = requestData.image_id;
            previewItem.style.position = 'relative';
            
            previewGallery.appendChild(previewItem);
        }

        // Style the loaded image
        imgElement.style.position = 'absolute';
        imgElement.style.top = '0';
        imgElement.style.left = '0';
        imgElement.style.width = '100%';
        imgElement.style.height = '100%';
        imgElement.style.objectFit = 'cover';
        imgElement.style.zIndex = '2';
        imgElement.alt = 'Preview';
        
        // Find all existing images in this container
        const existingImages = previewItem.querySelectorAll('img');
        
        // Add the new image
        previewItem.appendChild(imgElement);
        
        // Remove placeholder if it exists
        const placeholder = previewItem.querySelector('.preview-placeholder');
        if (placeholder) {
            placeholder.remove();
        }
        
        // Add or update overlay
        let overlay = previewItem.querySelector('.image-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'image-overlay';
            overlay.innerHTML = '<span class="image-name">Processing...</span>';
            previewItem.appendChild(overlay);
        }
        overlay.style.zIndex = '3';
        
        // Remove old images after transition
        setTimeout(() => {
            existingImages.forEach(img => {
                if (img !== imgElement) {
                    img.remove();
                }
            });
        }, 100);
    }

    setupSocketIO() {
        this.socket = io();
        
        this.socket.on('connect', () => {
            console.log('Connected to server');
            this.socket.emit('join_monitoring');
        });

        this.socket.on('disconnect', () => {
            console.log('Disconnected from server');
        });

        this.socket.on('status_update', (data) => {
            this.updateImageStatus(data);
        });

        this.socket.on('processing_complete', (data) => {
            this.handleProcessingComplete(data);
        });

        this.socket.on('batch_progress', (data) => {
            this.updateBatchProgress(data);
        });

        this.socket.on('batch_complete', (data) => {
            this.handleBatchComplete(data);
        });

        this.socket.on('batch_stopped', (data) => {
            this.handleBatchStopped(data);
        });

        this.socket.on('reprocess_complete', (data) => {
            this.handleReprocessComplete(data);
        });

        this.socket.on('processing_error', (data) => {
            this.showNotification('Processing Error', data.error, 'danger');
        });

        this.socket.on('preview_update', (data) => {
            this.updatePreviewImage(data);
        });

        this.socket.on('node_update', (data) => {
            this.updateNodeStatus(data);
        });

        this.socket.on('progress_update', (data) => {
            this.updateProgressStatus(data);
        });
    }

    setupEventListeners() {
        // File input change
        document.getElementById('fileInput').addEventListener('change', () => {
            this.handleFileUpload();
        });

        // Upload button
        document.getElementById('uploadBtn').addEventListener('click', () => {
            this.handleFileUpload();
        });

        // Clear queue button
        document.getElementById('clearQueueBtn').addEventListener('click', () => {
            this.clearUploadQueue();
        });

        // Process button
        document.getElementById('processBtn').addEventListener('click', () => {
            this.startProcessing();
        });

        // Reset button
        document.getElementById('resetBtn').addEventListener('click', () => {
            this.resetApplication();
        });

        // Refresh button
        document.getElementById('refreshBtn').addEventListener('click', () => {
            this.refreshStatus();
        });

        // Download archive button
        document.getElementById('downloadArchiveBtn').addEventListener('click', () => {
            this.downloadArchive();
        });

        // Re-processing buttons
        document.getElementById('reprocessBtn').addEventListener('click', () => {
            this.startReprocessing();
        });

        document.getElementById('clearReprocessBtn').addEventListener('click', () => {
            this.clearReprocessQueue();
        });

        // Previews toggle
        const previewsToggle = document.getElementById('previewsToggle');
        if (previewsToggle) {
            previewsToggle.addEventListener('change', (e) => {
                this.previewsEnabled = e.target.checked;
                this.saveUserPreferences();
                
                const previewGallery = document.getElementById('livePreview');
                
                if (!this.previewsEnabled) {
                    // Clear existing previews when disabling
                    if (previewGallery) {
                        // Only show disabled message if there are no active previews
                        const hasActivePreviews = previewGallery.querySelector('[data-preview-id]');
                        if (!hasActivePreviews) {
                            previewGallery.innerHTML = '<div class="empty-state"><i class="fas fa-eye-slash"></i><p>Live previews disabled</p></div>';
                        }
                    }
                    // Clear pending requests and counters
                    this.pendingPreviewsByGpu.clear();
                    this.droppedPreviews = 0;
                } else {
                    // Clear the disabled message when enabling
                    if (previewGallery) {
                        const emptyState = previewGallery.querySelector('.empty-state');
                        if (emptyState && emptyState.textContent.includes('disabled')) {
                            previewGallery.innerHTML = '';
                        }
                    }
                    // Refresh to get any current previews
                    this.refreshStatus();
                }
                
                this.showNotification(
                    'Preview Settings', 
                    `Live previews ${this.previewsEnabled ? 'enabled' : 'disabled'}`, 
                    'info'
                );
            });
        }

        // Delete buttons (delegated event handling)
        document.addEventListener('click', (e) => {
            if (e.target.closest('.delete-btn')) {
                const imageId = e.target.closest('.delete-btn').dataset.id;
                this.deleteImage(imageId);
            }
        });

        // Mark for re-processing buttons (delegated event handling)
        document.addEventListener('click', (e) => {
            if (e.target.closest('.mark-reprocess-btn')) {
                const imageId = e.target.closest('.mark-reprocess-btn').dataset.id;
                this.markForReprocessing(imageId);
            }
        });

        // Unmark from re-processing buttons (delegated event handling)
        document.addEventListener('click', (e) => {
            if (e.target.closest('.unmark-reprocess-btn')) {
                const imageId = e.target.closest('.unmark-reprocess-btn').dataset.id;
                this.unmarkForReprocessing(imageId);
            }
        });

        // Image click for full view (delegated event handling)
        document.addEventListener('click', (e) => {
            // Check if clicked on an image inside resultsGallery
            const imageItem = e.target.closest('#resultsGallery .image-item');
            if (imageItem && !e.target.closest('.btn')) {  // Changed: also exclude any button click
                const img = imageItem.querySelector('img');
                const imageId = imageItem.dataset.id;
                if (img) {
                    this.showImageModal(img.src, img.alt, imageId);
                }
            }
        });

        // Modal delete button
        document.getElementById('modalDeleteBtn').addEventListener('click', (e) => {
            const imageId = e.currentTarget.dataset.id;
            if (imageId) {
                this.deleteImageAndShowNext(imageId);
            }
        });

        // Pagination controls
        document.getElementById('itemsPerPage').addEventListener('change', (e) => {
            this.itemsPerPage = parseInt(e.target.value);
            this.currentPage = 1;
            this.renderResultsGallery();
        });

        // Show unrefined toggle
        document.getElementById('showUnrefinedToggle').addEventListener('change', (e) => {
            this.showUnrefined = e.target.checked;
            this.currentPage = 1;
            this.filterResults();
            this.renderResultsGallery();
        });

        // Pagination clicks (delegated)
        document.getElementById('resultsPagination').addEventListener('click', (e) => {
            if (e.target.closest('.page-link')) {
                e.preventDefault();
                const page = parseInt(e.target.closest('.page-link').dataset.page);
                if (page && !isNaN(page)) {
                    this.currentPage = page;
                    this.renderResultsGallery();
                }
            }
        });
    }

    setupDragAndDrop() {
        const fileInput = document.getElementById('fileInput');
        const uploadCard = fileInput.closest('.card');

        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            uploadCard.addEventListener(eventName, this.preventDefaults, false);
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            uploadCard.addEventListener(eventName, () => {
                uploadCard.classList.add('drag-over');
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            uploadCard.addEventListener(eventName, () => {
                uploadCard.classList.remove('drag-over');
            });
        });

        uploadCard.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            this.uploadFiles(files);
        });
    }

    preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            const modal = document.getElementById('imageModal');
            const modalInstance = bootstrap.Modal.getInstance(modal);
            
            if (modalInstance && modalInstance._isShown) {
                if (e.key === 'ArrowLeft') {
                    this.navigateImage('prev');
                } else if (e.key === 'ArrowRight') {
                    this.navigateImage('next');
                } else if (e.key === 'Delete') {
                    e.preventDefault();
                    document.getElementById('modalDeleteBtn').click();
                }
            }
        });
    }

    navigateImage(direction) {
        const currentImage = document.getElementById('modalImage');
        const currentSrc = currentImage.src;
        
        // Get all visible image items to get their data
        const allImageItems = Array.from(document.querySelectorAll('#resultsGallery .image-item'));
        const allImagesData = allImageItems.map(item => ({
            src: item.querySelector('img').src,
            alt: item.querySelector('img').alt,
            id: item.dataset.id
        }));
        
        const currentIndex = allImagesData.findIndex(imgData => imgData.src === currentSrc);
        
        if (currentIndex === -1) return;
        
        let newIndex;
        if (direction === 'prev') {
            newIndex = currentIndex > 0 ? currentIndex - 1 : allImagesData.length - 1;
        } else {
            newIndex = currentIndex < allImagesData.length - 1 ? currentIndex + 1 : 0;
        }
        
        const newImageData = allImagesData[newIndex];
        if (newImageData) {
            this.showImageModal(newImageData.src, newImageData.alt, newImageData.id);
        }
    }

    async handleFileUpload() {
        const fileInput = document.getElementById('fileInput');
        const files = fileInput.files;
        
        if (files.length === 0) {
            this.showNotification('No Files', 'Please select files to upload', 'warning');
            return;
        }

        await this.uploadFiles(files);
        fileInput.value = ''; // Clear the input
    }

    async uploadFiles(files) {
        const formData = new FormData();
        
        // Add files to form data
        for (let file of files) {
            formData.append('files', file);
        }

        try {
            this.setLoading('uploadBtn', true);
            this.updateStatus('Uploading files...');

            const response = await fetch('/upload', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (result.status === 'success') {
                this.showNotification('Upload Success', result.message, 'success');
                this.refreshStatus();
            } else {
                this.showNotification('Upload Error', result.message, 'danger');
            }
        } catch (error) {
            console.error('Upload error:', error);
            this.showNotification('Upload Error', 'Failed to upload files', 'danger');
        } finally {
            this.setLoading('uploadBtn', false);
        }
    }

    async clearUploadQueue() {
        try {
            this.setLoading('clearQueueBtn', true);
            
            const response = await fetch('/clear_queue', {
                method: 'POST'
            });

            const result = await response.json();
            
            if (result.status === 'success') {
                this.showNotification('Queue Cleared', result.message, 'success');
                this.refreshStatus();
            } else {
                this.showNotification('Error', result.message, 'danger');
            }
        } catch (error) {
            console.error('Clear queue error:', error);
            this.showNotification('Error', 'Failed to clear queue', 'danger');
        } finally {
            this.setLoading('clearQueueBtn', false);
        }
    }

    async startProcessing() {
        const positivePrompt = document.getElementById('positivePrompt').value;
        const negativePrompt = document.getElementById('negativePrompt').value;
        const saveUnrefined = document.getElementById('saveUnrefinedToggle').checked;
        
        // Get custom settings from the form
        const customSettings = this.getCustomSettings();

        try {
            this.setLoading('processBtn', true);
            this.updateStatus('Starting processing...');
            this.isProcessing = true;
            
            const response = await fetch('/process', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    positive_prompt: positivePrompt,
                    negative_prompt: negativePrompt,
                    save_unrefined: saveUnrefined,
                    ...customSettings
                })
            });

            const result = await response.json();
            
            if (result.status === 'success') {
                this.showNotification('Processing Started', result.message, 'success');
                this.showProgressBar();
                this.setProcessingState(true);
            } else {
                this.showNotification('Processing Error', result.message, 'danger');
                this.resetProcessButton();
            }
        } catch (error) {
            console.error('Processing error:', error);
            this.showNotification('Processing Error', 'Failed to start processing', 'danger');
            this.resetProcessButton();
        }
    }

    async stopProcessing() {
        if (!this.isProcessing) {
            return;  // Don't stop if not processing
        }
        
        try {
            const response = await fetch('/stop', {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                this.showNotification('Stopping', result.message, 'warning');
                this.updateStatus('Stopping batch processing...');
                
                // Disable the stop button while stopping
                const processBtn = document.getElementById('processBtn');
                processBtn.disabled = true;
                processBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Stopping...';
            } else {
                this.showNotification('Error', result.message, 'danger');
            }
        } catch (error) {
            console.error('Stop error:', error);
            this.showNotification('Error', 'Failed to stop processing', 'danger');
        }
    }

    getCustomSettings() {
        return {
            model: document.getElementById('modelSelect')?.value || 'juggernaut-ragnarok.safetensors',
            main_steps: parseInt(document.getElementById('mainSteps')?.value) || 80,
            main_cfg: parseFloat(document.getElementById('mainCfg')?.value) || 4.0,
            main_sampler: document.getElementById('mainSampler')?.value || 'dpmpp_2m_sde_gpu',
            main_scheduler: document.getElementById('mainScheduler')?.value || 'karras',
            refiner_steps: parseInt(document.getElementById('refinerSteps')?.value) || 80,
            refiner_cfg: parseFloat(document.getElementById('refinerCfg')?.value) || 4.0,
            refiner_sampler: document.getElementById('refinerSampler')?.value || 'dpmpp_2m_sde_gpu',
            refiner_scheduler: document.getElementById('refinerScheduler')?.value || 'karras',
            refiner_denoise: parseFloat(document.getElementById('refinerDenoise')?.value) || 0.4,
            refiner_cycles: parseInt(document.getElementById('refinerCycles')?.value) || 2
        };
    }

    setProcessingState(processing) {
        this.isProcessing = processing;
        const processBtn = document.getElementById('processBtn');
        
        if (processing) {
            // Show stop button with enhanced styling
            processBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Processing';
            processBtn.classList.remove('btn-success');
            processBtn.classList.add('btn-danger', 'processing');
            processBtn.disabled = false;
            processBtn.onclick = () => this.stopProcessing();
        } else {
            this.resetProcessButton();
        }
    }

    resetProcessButton() {
        this.isProcessing = false;
        const processBtn = document.getElementById('processBtn');
        processBtn.innerHTML = '<i class="fas fa-play"></i> Process Images';
        processBtn.classList.remove('btn-danger', 'processing');
        processBtn.classList.add('btn-success');
        processBtn.disabled = false;
        processBtn.onclick = () => this.startProcessing();
    }

    async resetApplication() {
        if (!confirm('Are you sure you want to reset the application? This will stop any current processing, clear all queues, and delete all images.')) {
            return;
        }

        try {
            this.setLoading('resetBtn', true);
            
            const response = await fetch('/clear_results', {
                method: 'POST'
            });

            const result = await response.json();
            
            if (result.status === 'success') {
                this.showNotification('Application Reset', result.message, 'success');
                this.refreshStatus();
                // Also reset progress bar and status text
                this.hideProgressBar();
                this.updateStatus('Ready');
            } else {
                this.showNotification('Error', result.message, 'danger');
            }
        } catch (error) {
            console.error('Reset error:', error);
            this.showNotification('Error', 'Failed to reset application', 'danger');
        } finally {
            this.setLoading('resetBtn', false);
        }
    }

    async deleteImageAndShowNext(imageId) {
        // Find current image's index BEFORE deletion
        const currentSrc = document.getElementById('modalImage').src;
        const url = new URL(currentSrc);
        const currentPathname = url.pathname;
        let currentIndex = this.filteredResults.findIndex(result => `/outputs/${result.name}` === currentPathname);

        if (!confirm('Are you sure you want to delete this image?')) {
            return;
        }

        try {
            const response = await fetch(`/delete_image/${imageId}`);
            const result = await response.json();
            
            if (result.status === 'success') {
                this.showNotification('Image Deleted', result.message, 'success');
                
                // Await a full status refresh to update this.filteredResults
                await this.refreshStatus(); 
                
                if (this.filteredResults.length === 0) {
                    // No more images, close modal
                    const modal = bootstrap.Modal.getInstance(document.getElementById('imageModal'));
                    if (modal) modal.hide();
                } else {
                    // Show image at same index, or previous if it was the last one
                    const newIndex = Math.min(currentIndex, this.filteredResults.length - 1);
                    const newImageData = this.filteredResults[newIndex];
                    
                    if (newImageData) {
                        this.showImageModal(`/outputs/${newImageData.name}`, newImageData.name, newImageData.image_id);
                    } else {
                        // Fallback: close modal
                        const modal = bootstrap.Modal.getInstance(document.getElementById('imageModal'));
                        if (modal) modal.hide();
                    }
                }
            } else {
                this.showNotification('Delete Error', result.message, 'danger');
            }
        } catch (error) {
            console.error('Delete error:', error);
            this.showNotification('Delete Error', 'Failed to delete image', 'danger');
        }
    }

    async deleteImage(imageId) {
        if (!confirm('Are you sure you want to delete this image?')) {
            return;
        }

        try {
            const response = await fetch(`/delete_image/${imageId}`);
            const result = await response.json();
            
            if (result.status === 'success') {
                this.showNotification('Image Deleted', result.message, 'success');
                this.refreshStatus();
            } else {
                this.showNotification('Delete Error', result.message, 'danger');
            }
        } catch (error) {
            console.error('Delete error:', error);
            this.showNotification('Delete Error', 'Failed to delete image', 'danger');
        }
    }

    async downloadArchive() {
        try {
            // Include current filter setting in download
            const includeUnrefined = this.showUnrefined;
            window.open(`/download_archive?include_unrefined=${includeUnrefined}`, '_blank');
        } catch (error) {
            console.error('Download error:', error);
            this.showNotification('Download Error', 'Failed to download archive', 'danger');
        }
    }

    async markForReprocessing(imageId) {
        try {
            const response = await fetch(`/mark_reprocess/${imageId}`, {
                method: 'POST'
            });

            const result = await response.json();
            
            if (result.status === 'success') {
                this.showNotification('Marked for Re-processing', result.message, 'success');
                this.refreshStatus();
            } else {
                this.showNotification('Mark Error', result.message, 'danger');
            }
        } catch (error) {
            console.error('Mark reprocess error:', error);
            this.showNotification('Mark Error', 'Failed to mark image for re-processing', 'danger');
        }
    }

    async unmarkForReprocessing(imageId) {
        try {
            const response = await fetch(`/unmark_reprocess/${imageId}`, {
                method: 'POST'
            });

            const result = await response.json();
            
            if (result.status === 'success') {
                this.showNotification('Unmarked', result.message, 'success');
                this.refreshStatus();
            } else {
                this.showNotification('Unmark Error', result.message, 'danger');
            }
        } catch (error) {
            console.error('Unmark reprocess error:', error);
            this.showNotification('Unmark Error', 'Failed to unmark image', 'danger');
        }
    }

    async clearReprocessQueue() {
        if (!confirm('Are you sure you want to clear the re-processing queue?')) {
            return;
        }

        try {
            this.setLoading('clearReprocessBtn', true);
            
            const response = await fetch('/clear_reprocess_queue', {
                method: 'POST'
            });

            const result = await response.json();
            
            if (result.status === 'success') {
                this.showNotification('Queue Cleared', result.message, 'success');
                this.refreshStatus();
            } else {
                this.showNotification('Clear Error', result.message, 'danger');
            }
        } catch (error) {
            console.error('Clear reprocess queue error:', error);
            this.showNotification('Clear Error', 'Failed to clear re-processing queue', 'danger');
        } finally {
            this.setLoading('clearReprocessBtn', false);
        }
    }

    async startReprocessing() {
        const positivePrompt = document.getElementById('positivePrompt').value;
        const negativePrompt = document.getElementById('negativePrompt').value;
        const saveUnrefined = document.getElementById('saveUnrefinedToggle').checked;
        
        // Get custom settings from the form
        const customSettings = this.getCustomSettings();

        try {
            this.setLoading('reprocessBtn', true);
            this.updateStatus('Starting re-processing...');
            this.isProcessing = true;
            
            // Show stop button
            const reprocessBtn = document.getElementById('reprocessBtn');
            reprocessBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Re-processing';
            reprocessBtn.classList.remove('btn-warning');
            reprocessBtn.classList.add('btn-danger');
            reprocessBtn.onclick = () => this.stopProcessing();
            
            const response = await fetch('/reprocess', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    positive_prompt: positivePrompt,
                    negative_prompt: negativePrompt,
                    save_unrefined: saveUnrefined,
                    ...customSettings
                })
            });

            const result = await response.json();
            
            if (result.status === 'success') {
                this.showNotification('Re-processing Started', result.message, 'success');
                this.showProgressBar();
            } else {
                this.showNotification('Re-processing Error', result.message, 'danger');
                this.resetReprocessButton();
            }
        } catch (error) {
            console.error('Re-processing error:', error);
            this.showNotification('Re-processing Error', 'Failed to start re-processing', 'danger');
            this.resetReprocessButton();
        }
    }

    resetReprocessButton() {
        this.isProcessing = false;
        const reprocessBtn = document.getElementById('reprocessBtn');
        const reprocessCount = document.getElementById('reprocessCount').textContent;
        reprocessBtn.innerHTML = `<i class="fas fa-redo"></i> Re-process Marked (${reprocessCount})`;
        reprocessBtn.classList.remove('btn-danger');
        reprocessBtn.classList.add('btn-warning');
        reprocessBtn.disabled = reprocessCount === '0';
        reprocessBtn.onclick = () => this.startReprocessing();
        this.setLoading('reprocessBtn', false);
    }

    handleReprocessComplete(data) {
        this.hideProgressBar();
        this.resetReprocessButton();
        
        const message = `Re-processing complete! Processed: ${data.total_processed}, Completed: ${data.completed}, Failed: ${data.failed}`;
        this.updateStatus(message);
        this.showNotification('Re-processing Complete', message, 'success');
        
        // Refresh to show final results
        this.refreshStatus();
    }

    async refreshStatus() {
        try {
            const response = await fetch('/status');
            const data = await response.json();
            
            this.updateUploadGallery(data.upload_queue);
            this.updateReprocessGallery(data.reprocess_queue);
            this.updateResultsWithPagination(data.results);
            this.updateStatusTable(data.status_data);
            this.updateQueueCounter(data.queue_count);
            this.updateReprocessCounter(data.reprocess_count);
            this.updateLivePreview(data.preview_images || {});
        } catch (error) {
            console.error('Status refresh error:', error);
        }
    }

    updateUploadGallery(uploadQueue) {
        const gallery = document.getElementById('uploadGallery');
        gallery.innerHTML = '';

        uploadQueue.forEach(item => {
            const imageItem = document.createElement('div');
            imageItem.className = 'image-item fade-in-up';
            imageItem.dataset.id = item.id;
            
            const filename = item.path.split('/').pop();
            
            imageItem.innerHTML = `
                <img src="/uploads/${filename}" alt="${item.original_name}">
                <div class="image-overlay">
                    <span class="image-name">${item.original_name}</span>
                </div>
            `;
            
            gallery.appendChild(imageItem);
        });
    }

    updateResultsWithPagination(results) {
        this.allResults = results;
        this.filterResults();
        this.renderResultsGallery();
    }

    filterResults() {
        if (this.showUnrefined) {
            this.filteredResults = this.allResults;
        } else {
            // Filter out unrefined images (those without "_refined" in the name)
            this.filteredResults = this.allResults.filter(result => 
                result.name.includes('_refined') || result.name.includes('refined-')
            );
        }
    }

    renderResultsGallery() {
        const gallery = document.getElementById('resultsGallery');
        gallery.innerHTML = '';

        // Remove any existing results counter
        const existingCounter = gallery.parentElement.querySelector('.results-counter');
        if (existingCounter) {
            existingCounter.remove();
        }

        // Show empty state if no results
        if (this.filteredResults.length === 0) {
            gallery.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-images"></i>
                    <p>No images to display</p>
                </div>
            `;
            this.renderPagination(0);
            return;
        }

        // Calculate pagination
        const totalPages = Math.ceil(this.filteredResults.length / this.itemsPerPage);
        const startIndex = (this.currentPage - 1) * this.itemsPerPage;
        const endIndex = Math.min(startIndex + this.itemsPerPage, this.filteredResults.length);
        
        // Add results counter
        const resultsInfo = document.createElement('div');
        resultsInfo.className = 'results-counter mb-3';
        resultsInfo.textContent = `Showing ${startIndex + 1}-${endIndex} of ${this.filteredResults.length} images`;
        gallery.parentElement.insertBefore(resultsInfo, gallery);
        
        // Render current page items
        for (let i = startIndex; i < endIndex; i++) {
            const result = this.filteredResults[i];
            const imageItem = document.createElement('div');
            imageItem.className = 'image-item clickable fade-in-up';
            imageItem.dataset.id = result.image_id;
            imageItem.title = 'Click to view full size';
            
            imageItem.innerHTML = `
                <img src="/outputs/${result.name}" alt="${result.name}">
                <div class="image-overlay">
                    <span class="image-name">${result.name}</span>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-warning mark-reprocess-btn" data-id="${result.image_id}" title="Mark for re-processing">
                            <i class="fas fa-redo"></i>
                        </button>
                        <button class="btn btn-danger delete-btn" data-id="${result.image_id}" title="Delete">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            `;
            
            gallery.appendChild(imageItem);
        }

        // Render pagination
        this.renderPagination(totalPages);
    }

    renderPagination(totalPages) {
        const pagination = document.getElementById('resultsPagination');
        pagination.innerHTML = '';

        if (totalPages <= 1) return;

        // Previous button
        const prevLi = document.createElement('li');
        prevLi.className = `page-item ${this.currentPage === 1 ? 'disabled' : ''}`;
        prevLi.innerHTML = `
            <a class="page-link" href="#" data-page="${this.currentPage - 1}" aria-label="Previous">
                <span aria-hidden="true">&laquo;</span>
            </a>
        `;
        pagination.appendChild(prevLi);

        // Page numbers
        const maxVisiblePages = 7;
        let startPage = Math.max(1, this.currentPage - Math.floor(maxVisiblePages / 2));
        let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);
        
        if (endPage - startPage < maxVisiblePages - 1) {
            startPage = Math.max(1, endPage - maxVisiblePages + 1);
        }

        // First page + ellipsis
        if (startPage > 1) {
            const firstLi = document.createElement('li');
            firstLi.className = 'page-item';
            firstLi.innerHTML = `<a class="page-link" href="#" data-page="1">1</a>`;
            pagination.appendChild(firstLi);

            if (startPage > 2) {
                const ellipsisLi = document.createElement('li');
                ellipsisLi.className = 'page-item disabled';
                ellipsisLi.innerHTML = `<span class="page-link">...</span>`;
                pagination.appendChild(ellipsisLi);
            }
        }

        // Page numbers
        for (let i = startPage; i <= endPage; i++) {
            const li = document.createElement('li');
            li.className = `page-item ${i === this.currentPage ? 'active' : ''}`;
            li.innerHTML = `<a class="page-link" href="#" data-page="${i}">${i}</a>`;
            pagination.appendChild(li);
        }

        // Last page + ellipsis
        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                const ellipsisLi = document.createElement('li');
                ellipsisLi.className = 'page-item disabled';
                ellipsisLi.innerHTML = `<span class="page-link">...</span>`;
                pagination.appendChild(ellipsisLi);
            }

            const lastLi = document.createElement('li');
            lastLi.className = 'page-item';
            lastLi.innerHTML = `<a class="page-link" href="#" data-page="${totalPages}">${totalPages}</a>`;
            pagination.appendChild(lastLi);
        }

        // Next button
        const nextLi = document.createElement('li');
        nextLi.className = `page-item ${this.currentPage === totalPages ? 'disabled' : ''}`;
        nextLi.innerHTML = `
            <a class="page-link" href="#" data-page="${this.currentPage + 1}" aria-label="Next">
                <span aria-hidden="true">&raquo;</span>
            </a>
        `;
        pagination.appendChild(nextLi);
    }

    updateStatusTable(statusData) {
        const tbody = document.getElementById('statusTableBody');
        tbody.innerHTML = '';

        statusData.forEach(status => {
            const row = document.createElement('tr');
            const statusClass = `status-${status.status.split(':')[0].toLowerCase()}`;
            
            row.dataset.imageId = status.image_id;
            row.innerHTML = `
                <td>${status.filename}</td>
                <td><span class="badge ${statusClass}">${status.status}</span></td>
                <td>${status.gpu}</td>
                <td>${status.progress}%</td>
            `;
            
            tbody.appendChild(row);
        });
    }

    updateImageStatus(data) {
        // Track GPU assignment for this image
        if (data.image_id && data.gpu !== undefined) {
            this.imageGpuMapping.set(data.image_id, data.gpu);
        }

        // Update status table by image_id first, then fallback to filename
        let row = document.querySelector(`#statusTableBody tr[data-image-id="${data.image_id}"]`);
        
        // If not found by image_id and we have a filename, try to find by filename
        if (!row && data.filename) {
            const rows = document.querySelectorAll('#statusTableBody tr');
            rows.forEach(r => {
                if (r.cells[0].textContent === data.filename) {
                    row = r;
                    // Also set the data-image-id attribute for future updates
                    if (data.image_id) {
                        row.dataset.imageId = data.image_id;
                    }
                }
            });
        }
        
        if (row) {
            const statusBadge = row.cells[1].querySelector('.badge');
            const statusClass = `status-${data.status.toLowerCase()}`;
            statusBadge.className = `badge ${statusClass}`;
            statusBadge.textContent = data.status;
            row.cells[3].textContent = `${data.progress || 0}%`;
            
            // Update GPU column if provided
            if (data.gpu !== undefined) {
                row.cells[2].textContent = data.gpu;
            }
        }

        // Add processing indicator if processing
        if (data.status === 'processing') {
            const imageItem = document.querySelector(`[data-id="${data.image_id}"]`);
            if (imageItem) {
                imageItem.classList.add('processing-indicator');
            }
        }
    }

    handleProcessingComplete(data) {
        // Refresh results gallery to show new images
        this.refreshStatus();
        
        // Remove processing indicator
        const imageItem = document.querySelector(`[data-id="${data.image_id}"]`);
        if (imageItem) {
            imageItem.classList.remove('processing-indicator');
        }
        
        // Remove preview for this image
        const previewItem = document.querySelector(`[data-preview-id="${data.image_id}"]`);
        if (previewItem) {
            previewItem.remove();
        }
        
        // Clean up GPU mapping for completed image
        if (data.image_id) {
            this.imageGpuMapping.delete(data.image_id);
        }
    }

    updateBatchProgress(data) {
        const progressBar = document.getElementById('progressBar');
        const progressText = document.getElementById('progressText');
        
        const percentage = (data.completed / data.total) * 100;
        progressBar.style.width = `${percentage}%`;
        progressText.textContent = `${data.completed}/${data.total} images processed`;
        
        this.updateStatus(`Processing: ${data.completed}/${data.total} images completed`);
    }

    handleBatchComplete(data) {
        this.hideProgressBar();
        this.setProcessingState(false);
        this.resetReprocessButton();
        
        const message = `Batch complete! Processed: ${data.total_processed}, Completed: ${data.completed}, Failed: ${data.failed}`;
        this.updateStatus(message);
        this.showNotification('Batch Complete', message, 'success');
        
        // Refresh to show final results
        this.refreshStatus();
    }

    handleBatchStopped(data) {
        this.hideProgressBar();
        this.setProcessingState(false);
        this.resetReprocessButton();
        
        const message = `Batch stopped! Completed: ${data.completed}/${data.total} images`;
        this.updateStatus(message);
        this.showNotification('Batch Stopped', message, 'warning');
        
        // Refresh to show final results
        this.refreshStatus();
    }

    showProgressBar() {
        const container = document.getElementById('progressContainer');
        container.style.display = 'block';
        
        const progressBar = document.getElementById('progressBar');
        progressBar.style.width = '0%';
        
        const progressText = document.getElementById('progressText');
        progressText.textContent = '0/0 images processed';
    }

    hideProgressBar() {
        const container = document.getElementById('progressContainer');
        container.style.display = 'none';
    }

    updateStatus(message) {
        const statusText = document.getElementById('statusText');
        statusText.textContent = message;
        statusText.className = 'alert alert-info';
    }

    updateQueueCounter(count) {
        const counter = document.getElementById('queueCounter');
        counter.textContent = `${count} images in queue`;
    }

    updateReprocessGallery(reprocessQueue) {
        const gallery = document.getElementById('reprocessGallery');
        gallery.innerHTML = '';

        reprocessQueue.forEach(item => {
            const imageItem = document.createElement('div');
            imageItem.className = 'image-item reprocess-item fade-in-up';
            imageItem.dataset.id = item.image_id;
            
            const filename = item.path.split('/').pop();
            
            imageItem.innerHTML = `
                <img src="/uploads/${filename}" alt="${item.original_name}">
                <div class="image-overlay">
                    <span class="image-name">${item.original_name}</span>
                    <button class="btn btn-sm btn-danger unmark-reprocess-btn" data-id="${item.image_id}">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            `;
            
            gallery.appendChild(imageItem);
        });
    }

    updateReprocessCounter(count) {
        const counter = document.getElementById('reprocessCount');
        counter.textContent = count;
        
        // Enable/disable reprocess button based on queue count
        const reprocessBtn = document.getElementById('reprocessBtn');
        reprocessBtn.disabled = count === 0;
    }

    setLoading(buttonId, loading) {
        const button = document.getElementById(buttonId);
        const icon = button.querySelector('i');
        
        if (loading) {
            button.disabled = true;
            button.classList.add('loading');
            if (icon) {
                icon.className = 'fas fa-spinner fa-spin';
            }
        } else {
            button.disabled = false;
            button.classList.remove('loading');
            if (icon) {
                // Restore original icon based on button
                const iconMap = {
                    'uploadBtn': 'fas fa-plus',
                    'processBtn': 'fas fa-play',
                    'clearQueueBtn': 'fas fa-trash',
                    'resetBtn': 'fas fa-undo',
                    'reprocessBtn': 'fas fa-redo',
                    'clearReprocessBtn': 'fas fa-times'
                };
                icon.className = iconMap[buttonId] || 'fas fa-cog';
            }
        }
    }

    showNotification(title, message, type = 'info') {
        const toast = document.getElementById('notificationToast');
        const toastMessage = document.getElementById('toastMessage');
        
        // Set message
        toastMessage.textContent = message;
        
        // Set type styling
        toast.className = `toast border-${type}`;
        
        // Show toast
        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();
    }

    startStatusPolling() {
        // Poll status every 2 seconds when not using websockets for updates
        setInterval(() => {
            if (!this.socket || !this.socket.connected) {
                this.refreshStatus();
            }
        }, 2000);
    }

    updatePreviewImage(data) {
        if (!this.previewsEnabled) {
            return;
        }
        
        // Queue the preview request instead of processing immediately
        this.queuePreviewRequest(data);
    }

    updateNodeStatus(data) {
        // Update node information in status display
        console.log(`Image ${data.image_id} executing node: ${data.node}`);
    }

    updateProgressStatus(data) {
        // Update progress for specific image
        const row = document.querySelector(`#statusTableBody tr[data-image-id="${data.image_id}"]`);
        if (row) {
            row.cells[3].textContent = `${data.progress}%`;
        }
    }

    updateLivePreview(previewImages) {
        const previewGallery = document.getElementById('livePreview');
        if (!previewGallery) {
            return;
        }
        
        // Only show disabled message if previews are disabled AND there are no preview images
        if (!this.previewsEnabled) {
            // Check if we need to clear the gallery
            const hasContent = previewGallery.querySelector('[data-preview-id]') || 
                              (Object.keys(previewImages).length > 0);
            
            if (!hasContent) {
                previewGallery.innerHTML = '<div class="empty-state"><i class="fas fa-eye-slash"></i><p>Live previews disabled</p></div>';
            }
            return;
        }
        
        // Clear the disabled message if it exists when previews are enabled
        const emptyState = previewGallery.querySelector('.empty-state');
        if (emptyState && emptyState.textContent.includes('disabled')) {
            emptyState.remove();
        }

        // Get existing preview items
        const existingPreviews = new Set(
            Array.from(previewGallery.querySelectorAll('[data-preview-id]'))
                .map(el => el.dataset.previewId)
        );

        // Update or add preview images
        Object.entries(previewImages).forEach(([imageId, previewPath]) => {
            // Use the same update method for consistency
            const imageSrc = previewPath.startsWith('http') 
                ? previewPath 
                : `/previews/${previewPath.split('/').pop()}`;
            
            this.queuePreviewRequest({
                image_id: imageId,
                [previewPath.startsWith('http') ? 'preview_url' : 'preview_path']: imageSrc
            });
            
            existingPreviews.delete(imageId);
        });

        // Remove previews that are no longer in the list
        existingPreviews.forEach(imageId => {
            const previewItem = previewGallery.querySelector(`[data-preview-id="${imageId}"]`);
            if (previewItem) {
                previewItem.remove();
            }
        });
    }

    showImageModal(imageSrc, imageName, imageId) {
        // Update modal content
        const modalImage = document.getElementById('modalImage');
        const modalTitle = document.getElementById('imageModalLabel');
        const imageInfo = document.getElementById('imageInfo');
        const downloadLink = document.getElementById('downloadLink');
        const modalDeleteBtn = document.getElementById('modalDeleteBtn');
        
        modalImage.src = imageSrc;
        modalTitle.textContent = imageName || 'Image Preview';
        
        // Set download link
        downloadLink.href = imageSrc;
        downloadLink.download = imageName || 'image.png';

        // Store imageId on the delete button
        if (imageId) {
            modalDeleteBtn.dataset.id = imageId;
            modalDeleteBtn.style.display = 'inline-block';
        } else {
            modalDeleteBtn.style.display = 'none';
        }
        
        // Load image to get dimensions
        const img = new Image();
        img.onload = function() {
            imageInfo.textContent = `${this.width} × ${this.height} pixels`;
        };
        img.src = imageSrc;
        
        // Get existing modal instance or create new one
        const modalElement = document.getElementById('imageModal');
        let modal = bootstrap.Modal.getInstance(modalElement);
        
        if (!modal) {
            modal = new bootstrap.Modal(modalElement);
        }
        
        // Only show if not already shown
        if (!modal._isShown) {
            modal.show();
        }
    }

    async loadAvailableModels() {
        try {
            const response = await fetch('/get_models');
            const data = await response.json();
            
            if (data.status === 'success') {
                // Populate model dropdown
                const modelSelect = document.getElementById('modelSelect');
                if (modelSelect) {
                    modelSelect.innerHTML = '';
                    data.models.forEach(model => {
                        const option = document.createElement('option');
                        option.value = model;
                        option.textContent = model;
                        if (model === 'juggernaut-ragnarok.safetensors') {
                            option.selected = true;
                        }
                        modelSelect.appendChild(option);
                    });
                }
                
                // Populate sampler dropdowns
                const samplerSelects = ['mainSampler', 'refinerSampler'];
                samplerSelects.forEach(id => {
                    const select = document.getElementById(id);
                    if (select) {
                        select.innerHTML = '';
                        data.samplers.forEach(sampler => {
                            const option = document.createElement('option');
                            option.value = sampler;
                            option.textContent = sampler;
                            if (sampler === 'dpmpp_2m_sde_gpu') {
                                option.selected = true;
                            }
                            select.appendChild(option);
                        });
                    }
                });
                
                // Populate scheduler dropdowns
                const schedulerSelects = ['mainScheduler', 'refinerScheduler'];
                schedulerSelects.forEach(id => {
                    const select = document.getElementById(id);
                    if (select) {
                        select.innerHTML = '';
                        data.schedulers.forEach(scheduler => {
                            const option = document.createElement('option');
                            option.value = scheduler;
                            option.textContent = scheduler;
                            if (scheduler === 'karras') {
                                option.selected = true;
                            }
                            select.appendChild(option);
                        });
                    }
                });
                
                console.log('Models and samplers loaded successfully');
            } else {
                console.warn('Failed to load models:', data.message);
                this.showNotification('Warning', 'Failed to load available models. Using defaults.', 'warning');
            }
        } catch (error) {
            console.error('Error loading models:', error);
            this.showNotification('Warning', 'Failed to load available models. Using defaults.', 'warning');
        }
    }
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.comfyApp = new ComfyUIApp();
});