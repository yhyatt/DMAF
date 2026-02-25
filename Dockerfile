FROM python:3.10-slim

# Install system dependencies needed for image processing and face recognition
RUN apt-get update && apt-get install -y \
    # Build tools for compiling InsightFace Cython extensions
    build-essential \
    g++ \
    # For InsightFace and image processing
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package definition
COPY pyproject.toml README.md ./

# Copy source code
COPY src/ src/

# Known people images are downloaded from GCS at runtime via known_people_gcs_uri

# Install DMAF with InsightFace backend (lighter than face_recognition, no cmake needed)
RUN pip install --no-cache-dir -e ".[insightface,gcs]" google-cloud-firestore

# Pre-download InsightFace model to avoid cold-start download in cloud
# This adds ~600MB to image but eliminates 3-5 second startup delay
RUN python -c "from insightface.app import FaceAnalysis; app = FaceAnalysis(name='buffalo_l'); app.prepare(ctx_id=-1)"

# Copy config template
COPY config.example.yaml /app/config.example.yaml

# Run in batch mode by default
# Override with docker run args or Cloud Run Job args
ENTRYPOINT ["python", "-m", "dmaf"]
CMD ["--scan-once", "--config", "/config/config.yaml"]
