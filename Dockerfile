# ============================================================
# Stage 1: C++ Build Stage
# Compiles hft_engine pybind11 .so from source on Linux
# ============================================================
FROM python:3.11-slim AS cpp-builder

# Install C++ build tools and cmake
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    g++ \
    python3-dev \
    pybind11-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY the C++ source into the builder stage
WORKDIR /cpp_build
COPY engine/backend_cpp/ ./

# Build the pybind11 module
RUN mkdir -p build && cd build && \
    cmake -DCMAKE_BUILD_TYPE=Release \
          -DPYBIND11_FINDPYTHON=ON \
          .. && \
    make -j$(nproc)

# ============================================================
# Stage 2: Python Runtime Stage
# ============================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled .so from the build stage into the engine build dir
# so trading_env.py can find it at: engine/backend_cpp/build/hft_engine*.so
COPY --from=cpp-builder /cpp_build/build/ /app/engine/backend_cpp/build/

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full application source
COPY api/ ./api/
COPY engine/ ./engine/
COPY worker/ ./worker/
RUN mkdir -p ./data/

# Copy start script
COPY start.sh .
RUN chmod +x start.sh

# Expose FastAPI port
EXPOSE 8000

# Default command: start FastAPI only. 
# (Celery worker must be run separately due to 512MB free tier RAM limits)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
