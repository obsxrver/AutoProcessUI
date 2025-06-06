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
        
        this.init();
    }

    init() {
        this.setupSocketIO();
        this.setupEventListeners();
        this.setupDragAndDrop();
        this.setupKeyboardShortcuts();
        this.startStatusPolling();
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

        // Clear all results button
        document.getElementById('clearAllBtn').addEventListener('click', () => {
            this.clearAllResults();
        });

        // Refresh button
        document.getElementById('refreshBtn').addEventListener('click', () => {
            this.refreshStatus();
        });

        // Download archive button
        document.getElementById('downloadArchiveBtn').addEventListener('click', () => {
            this.downloadArchive();
        });

        // Delete buttons (delegated event handling)
        document.addEventListener('click', (e) => {
            if (e.target.closest('.delete-btn')) {
                const imageId = e.target.closest('.delete-btn').dataset.id;
                this.deleteImage(imageId);
            }
        });

        // Image click for full view (delegated event handling)
        document.addEventListener('click', (e) => {
            // Check if clicked on an image inside resultsGallery
            const imageItem = e.target.closest('#resultsGallery .image-item');
            if (imageItem && !e.target.closest('.delete-btn')) {
                const img = imageItem.querySelector('img');
                if (img) {
                    this.showImageModal(img.src, img.alt);
                }
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
                }
            }
        });
    }

    navigateImage(direction) {
        const currentImage = document.getElementById('modalImage');
        const currentSrc = currentImage.src;
        
        // Get all result images
        const allImages = Array.from(document.querySelectorAll('#resultsGallery .image-item img'));
        const currentIndex = allImages.findIndex(img => img.src === currentSrc);
        
        if (currentIndex === -1) return;
        
        let newIndex;
        if (direction === 'prev') {
            newIndex = currentIndex > 0 ? currentIndex - 1 : allImages.length - 1;
        } else {
            newIndex = currentIndex < allImages.length - 1 ? currentIndex + 1 : 0;
        }
        
        const newImage = allImages[newIndex];
        if (newImage) {
            this.showImageModal(newImage.src, newImage.alt);
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

        try {
            this.setLoading('processBtn', true);
            this.updateStatus('Starting processing...');
            this.isProcessing = true;
            
            // Show stop button
            const processBtn = document.getElementById('processBtn');
            processBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Processing';
            processBtn.classList.remove('btn-success');
            processBtn.classList.add('btn-danger');
            processBtn.onclick = () => this.stopProcessing();
            
            const response = await fetch('/process', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    positive_prompt: positivePrompt,
                    negative_prompt: negativePrompt,
                    save_unrefined: saveUnrefined
                })
            });

            const result = await response.json();
            
            if (result.status === 'success') {
                this.showNotification('Processing Started', result.message, 'success');
                this.showProgressBar();
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

    resetProcessButton() {
        this.isProcessing = false;
        const processBtn = document.getElementById('processBtn');
        processBtn.innerHTML = '<i class="fas fa-play"></i> Process Images';
        processBtn.classList.remove('btn-danger');
        processBtn.classList.add('btn-success');
        processBtn.disabled = false;
        processBtn.onclick = () => this.startProcessing();
    }

    async clearAllResults() {
        if (!confirm('Are you sure you want to clear all results? This will delete all processed images.')) {
            return;
        }

        try {
            this.setLoading('clearAllBtn', true);
            
            const response = await fetch('/clear_results', {
                method: 'POST'
            });

            const result = await response.json();
            
            if (result.status === 'success') {
                this.showNotification('Results Cleared', result.message, 'success');
                this.refreshStatus();
            } else {
                this.showNotification('Error', result.message, 'danger');
            }
        } catch (error) {
            console.error('Clear results error:', error);
            this.showNotification('Error', 'Failed to clear results', 'danger');
        } finally {
            this.setLoading('clearAllBtn', false);
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

    async refreshStatus() {
        try {
            const response = await fetch('/status');
            const data = await response.json();
            
            this.updateUploadGallery(data.upload_queue);
            this.updateResultsWithPagination(data.results);
            this.updateStatusTable(data.status_data);
            this.updateQueueCounter(data.queue_count);
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
                    <button class="btn btn-sm btn-danger delete-btn" data-id="${result.image_id}">
                        <i class="fas fa-trash"></i>
                    </button>
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
        // Update status table if image exists
        const rows = document.querySelectorAll('#statusTableBody tr');
        rows.forEach(row => {
            const filename = row.cells[0].textContent;
            if (filename === data.filename) {
                const statusBadge = row.cells[1].querySelector('.badge');
                const statusClass = `status-${data.status.toLowerCase()}`;
                statusBadge.className = `badge ${statusClass}`;
                statusBadge.textContent = data.status;
                row.cells[3].textContent = `${data.progress || 0}%`;
            }
        });

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
        this.resetProcessButton();
        
        const message = `Batch complete! Processed: ${data.total_processed}, Completed: ${data.completed}, Failed: ${data.failed}`;
        this.updateStatus(message);
        this.showNotification('Batch Complete', message, 'success');
        
        // Refresh to show final results
        this.refreshStatus();
    }

    handleBatchStopped(data) {
        this.hideProgressBar();
        this.resetProcessButton();
        
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
                    'clearAllBtn': 'fas fa-trash-alt'
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
        // Update live preview gallery with new preview
        const previewGallery = document.getElementById('livePreview');
        if (!previewGallery) return;

        // Find or create preview item container
        let previewItem = previewGallery.querySelector(`[data-preview-id="${data.image_id}"]`);
        
        if (!previewItem) {
            previewItem = document.createElement('div');
            previewItem.className = 'image-item preview-container fade-in-up';
            previewItem.dataset.previewId = data.image_id;
            previewItem.style.position = 'relative';
            
            // Add a loading placeholder
            const placeholder = document.createElement('div');
            placeholder.className = 'preview-placeholder';
            placeholder.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            previewItem.appendChild(placeholder);
            
            previewGallery.appendChild(previewItem);
        }

        // Create new image element
        const newImg = document.createElement('img');
        newImg.style.position = 'absolute';
        newImg.style.top = '0';
        newImg.style.left = '0';
        newImg.style.width = '100%';
        newImg.style.height = '100%';
        newImg.style.objectFit = 'cover';
        newImg.style.zIndex = '2';
        newImg.alt = 'Preview';
        
        // Set the source
        if (data.preview_path) {
            newImg.src = data.preview_path;
        } else if (data.preview_url) {
            newImg.src = data.preview_url;
        }

        // When new image loads, add it and remove old ones
        newImg.onload = () => {
            // Find all existing images in this container
            const existingImages = previewItem.querySelectorAll('img');
            
            // Add the new image
            previewItem.appendChild(newImg);
            
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
            overlay.style.zIndex = '3'; // Keep overlay on top
            
            // Remove old images after a short delay to ensure smooth transition
            setTimeout(() => {
                existingImages.forEach(img => {
                    if (img !== newImg) {
                        img.remove();
                    }
                });
            }, 100);
        };

        // Handle error case
        newImg.onerror = () => {
            console.error('Failed to load preview image');
        };
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
        if (!previewGallery) return;

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
            
            this.updatePreviewImage({
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

    showImageModal(imageSrc, imageName) {
        // Update modal content
        const modalImage = document.getElementById('modalImage');
        const modalTitle = document.getElementById('imageModalLabel');
        const imageInfo = document.getElementById('imageInfo');
        const downloadLink = document.getElementById('downloadLink');
        
        modalImage.src = imageSrc;
        modalTitle.textContent = imageName || 'Image Preview';
        
        // Set download link
        downloadLink.href = imageSrc;
        downloadLink.download = imageName || 'image.png';
        
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
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.comfyApp = new ComfyUIApp();
});