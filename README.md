# ⚡ HFT Hybrid Bot: C++ Microstructure & RL Market Maker

![C++](https://img.shields.io/badge/C++-17%2B-blue?style=flat-square&logo=c%2B%2B)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![Gymnasium](https://img.shields.io/badge/Gymnasium-RL-orange?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

An institutional-grade algorithmic trading architecture bridging a **bare-metal C++ limit order book (LOB) matching engine** with a **Python multi-core Reinforcement Learning (PPO)** agent. Engineered to capture maker rebates through passive market making, the system features $O(1)$ execution latency, absolute dollar volatility sizing, and Avellaneda-Stoikov reservation price skewing to dynamically hedge against adverse selection.

<p align="center">
  <img src="assets/evaluation_plot_historical.png" alt="Institutional Performance Chart" width="800">
</p>

## 🧠 System Architecture

The architecture rigorously separates high-frequency alpha generation from state-space risk management:

1. **The C++ Microstructure Core (`backend_cpp/`)**
   * **$O(1)$ Matching Engine:** Bypasses dynamic allocation using pre-allocated 64-byte L1 cache-aligned `MemorySlab` arrays and `BitTree` bit-shift math.
   * **Mathematical Oracle:** Natively computes the Avellaneda-Stoikov reservation price skew using absolute dollar volatility and exact physical asset exposure.
   * **Zero-Copy Telemetry:** Exposes real-time Order Book Imbalance (OBI) to Python via optimized Pybind11 wrappers.

2. **The Python RL Brain (`rl_trading/`)**
   * **PPO Pricing Agent:** Operates strictly as a quoting engine, outputting inventory risk aversion ($\gamma$) and stochastic spread multipliers.
   * **Passive Maker Clamp:** Mathematically enforces pure maker-rebate capture (-0.01% fee tier) by preventing limit orders from crossing the spread during flash crashes.
   * **Dynamic Circuit Breakers:** Governs strict physical maximum inventory limits (e.g., $\pm 6.0$ BTC) independent of the AI's quoting logic.

## 📂 Repository Structure

```text
hft-hybrid-bot/
├── backend_cpp/                 # Bare-metal C++ Core Engine
│   ├── CMakeLists.txt
│   ├── bindings/                # Pybind11 Python wrappers (pybind_module.cpp)
│   ├── include/                 # Hardware slabs, memory pools, and LOB logic
│   └── tests/                   # C++ unit tests
├── rl_trading/                  # Custom Gymnasium Environment
│   ├── __init__.py
│   └── envs/
│       ├── __init__.py
│       └── trading_env.py       # Physics, state-space accounting, and reward engineering
├── scripts/                     # Execution & Data Pipelines
│   ├── evaluate.py              # Telemetry and 3-panel plotting
│   ├── fetch_real_market_data.py # Binance AggTrade LOB reconstruction
│   └── train.py                 # Multi-core PPO training script
├── .gitignore
└── README.md
```

## 🚀 Quick Start

### 1. Prerequisites
* **CMake** (v3.15+)
* **C++ Compiler** supporting C++17 (GCC, Clang, or MSVC)
* **Python 3.10+**

### 2. Installation
Clone the repository and install the required dependencies (ensure `stable-baselines3`, `gymnasium`, and `pandas` are installed):
```bash
git clone [https://github.com/YOUR_USERNAME/hft-hybrid-bot.git](https://github.com/YOUR_USERNAME/hft-hybrid-bot.git)
cd hft-hybrid-bot
pip install -r requirements.txt
```

### 3. Compiling the C++ Engine
Compile the Pybind11 module to enable the Python environment to communicate with the C++ backend:
```bash
cd backend_cpp/build
cmake ..
cmake --build . --config Release
cd ../..
```

## 📊 Pipeline Execution

### Step 1: Real Market Data Ingestion
The engine features a high-speed parser tailored for historical tick data. Run the data fetcher to download and format real Binance `aggTrades` into a zero-allocation integer format.
```bash
python scripts/fetch_real_market_data.py
```

### Step 2: Multi-Core Training
Initiate the PPO training sequence. The agent will learn to widen spreads and skew its reservation price to survive adverse selection.
```bash
python scripts/train.py
```

### Step 3: Institutional Evaluation
Generate a professional 3-panel evaluation chart tracking Net Worth, Asset Mid-Price, and Physical Inventory Exposure to validate structural performance.
```bash
python scripts/evaluate.py
```

## 👨‍💻 Author
**Ronak Sharma**
*B.Tech in Electronics and Communication Engineering | Class of 2026*
Quantitative Developer specializing in C++ infrastructure, full-stack systems, and algorithmic trading architectures.

---
*Disclaimer: This software is built for educational and quantitative research purposes. It does not constitute financial advice and should not be deployed with live capital without extensive paper trading and risk management wrappers.*