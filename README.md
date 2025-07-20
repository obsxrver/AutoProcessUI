# AutoProcessUI

A multi-GPU batch image processing application for ComfyUI with both Gradio and Flask web interfaces.

## Features

- **Multi-GPU Processing**: Automatically distributes work across multiple GPUs
- **Batch Processing**: Process multiple images simultaneously 
- **Live Progress Updates**: Real-time status updates via WebSocket
- **Image Gallery**: View uploaded and processed images
- **Custom Prompts**: Configurable positive and negative prompts
- **Download Archives**: Batch download processed images as ZIP
- **Two Interface Options**: Choose between Gradio or Flask web interface
- **GPU-based Preview Management**: Throttles preview requests per GPU server to prevent overload
- **Intelligent Queueing**: Manages preview requests to ensure final images load properly
- **Instagram Import**: Fetch images from an Instagram profile with optional session caching and automatic single-human filtering

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set ComfyUI path (if not in default location):
```bash
export COMFYUI_PATH="/path/to/ComfyUI"
```

## Usage

### Flask Interface (Recommended)

The Flask version provides a modern, responsive web interface with better customization options.

```bash
python app.py
```

Access the interface at `http://localhost:5000`

**Features:**
- Modern Bootstrap UI
- Real-time WebSocket updates
- Drag & drop file uploads
- Interactive image galleries
- Progress bars and status indicators
- Toast notifications

### Gradio Interface

The original Gradio interface provides a simple, auto-generated UI.

```bash
python gradio_app.py
```

Access the interface at `http://localhost:7860`

**Features:**
- Auto-generated interface
- Built-in file handling
- Automatic refresh capabilities

### Startup Wrapper

For production deployment, use the startup wrapper:

```bash
python start_app.py
```

This will:
- Check environment setup
- Validate dependencies
- Launch the appropriate interface
- Handle error reporting

## Configuration

### Environment Variables

- `COMFYUI_PATH`: Path to ComfyUI installation (default: `/workspace/ComfyUI`)
- `FLASK_PORT`: Port for Flask app (default: `5000`)
- `GRADIO_PORT`: Port for Gradio app (default: `7860`)
- `CUDA_VISIBLE_DEVICES`: GPU devices to use (default: `0,1,2,3,4,5,6,7`)

### Workflow Configuration

Edit `workflow.json` to customize the ComfyUI processing workflow:
- Default prompts are extracted from nodes "10" (positive) and "15" (negative)
- Output nodes "20" and "52" are used for result images
- Input node "1" is automatically updated with uploaded images

## Preview Management Features

### GPU-based Preview Throttling

The application intelligently manages preview requests to prevent overloading the ComfyUI servers:

- **Per-GPU Limits**: Maximum of 2 concurrent preview requests per GPU/ComfyUI server
- **Smart Distribution**: Automatically distributes preview requests across available GPUs
- **Drop Policy**: Excess preview requests are dropped instead of queued to prioritize responsiveness

### Preview Controls

- **Toggle Control**: Enable/disable live previews entirely
- **Visual Feedback**: Shows active preview counts and dropped preview statistics
- **Persistent Settings**: Saves your preview preferences automatically

### Benefits

- **Prevents Server Overload**: Ensures ComfyUI servers aren't flooded with preview requests
- **Better Final Image Loading**: Prioritizes final processed images over excessive previews
- **Smooth Performance**: Maintains responsive interface even during heavy batch processing

The system automatically saves your preview preferences and restores them on page reload.

## File Structure

```
AutoProcessUI/
├── app.py                    # Flask application
├── gradio_app.py            # Gradio application  
├── batchProcess.py          # Core processing logic
├── comfyui_websocket.py     # WebSocket handling
├── start_app.py             # Startup wrapper
├── workflow.json            # ComfyUI workflow definition
├── requirements.txt         # Python dependencies
├── templates/
│   └── index.html          # Flask HTML template
├── static/
│   ├── style.css           # CSS styling
│   └── app.js              # JavaScript frontend
├── temp_inputs/            # Temporary upload storage
└── gradio_outputs/         # Processed image outputs
```

## API Endpoints (Flask)

- `GET /` - Main interface
- `POST /upload` - Upload images
- `POST /process` - Start processing
- `POST /clear_queue` - Clear upload queue
- `POST /clear_results` - Clear all results
- `GET /status` - Get processing status
- `GET /download_archive` - Download results archive
- `GET /outputs/<filename>` - Serve output images
- `GET /uploads/<filename>` - Serve uploaded images
- `GET /delete_image/<id>` - Delete specific image

## WebSocket Events (Flask)

- `status_update` - Individual image status changes
- `batch_progress` - Overall batch progress
- `batch_complete` - Batch processing finished
- `processing_error` - Error notifications

## Troubleshooting

### Common Issues

1. **ComfyUI not found**: Set `COMFYUI_PATH` environment variable
2. **GPU detection fails**: Install PyTorch with CUDA support
3. **Port conflicts**: Change port using environment variables
4. **Upload failures**: Check file permissions and disk space

### Testing

Run environment tests:
```bash
python test_startup.py
```

Run upload tests:
```bash
python test_upload.py
```

### Logs

- Flask logs: Console output
- Gradio logs: `/var/log/portal/batchprocessui.log` (if using supervisor)

## Deployment

### Production Setup

1. Use a production WSGI server like Gunicorn:
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

2. Configure reverse proxy (nginx/Apache)
3. Set up SSL certificates
4. Configure environment variables
5. Set up process monitoring

### Docker Deployment

Create a Dockerfile:
```dockerfile
FROM python:3.9
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
EXPOSE 5000
CMD ["python", "app.py"]
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes
4. Test thoroughly
5. Submit a pull request

## License

This project is open source. Please check the license file for details.

