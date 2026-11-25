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
    make -j$(nproc) && \
    ls *.so 2>/dev/null || (echo "ERROR: hft_engine .so not built!" && exit 1)

# ============================================================
# Stage 2: Python Runtime Stage
# ============================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Copy the full application source first
COPY api/ ./api/
COPY engine/ ./engine/
COPY worker/ ./worker/
COPY scripts/ ./scripts/
COPY data/studies/ ./data/studies/
RUN mkdir -p ./data/

# IMPORTANT: Copy compiled .so AFTER engine/ source copy so it is never overwritten.
# Optional direct C++ clients use this module; the legacy RL adapter is removed.
COPY --from=cpp-builder /cpp_build/build/ /app/engine/backend_cpp/build/

# Copy start script
COPY start.sh .
RUN chmod +x start.sh

# Expose FastAPI port
EXPOSE 8000

# Run the workbench in one API process.
CMD ["bash", "start.sh"]
