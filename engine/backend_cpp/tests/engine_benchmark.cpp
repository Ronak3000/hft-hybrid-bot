#include <iostream>
#include <chrono>
#include <vector>
#include <random>
#include <iomanip>
#include <memory>

// Include your exact engine headers
#include "order.h"
#include "memory_pool.h"
#include "hardware_slab.h"
#include "matching_engine.h"

using namespace std::chrono;

// Helpers for readable synthetic microbenchmark output.
void print_separator() {
    std::cout << "========================================================================" << std::endl;
}

void print_section(const std::string& name) {
    std::cout << "\n[STAGE] " << name << "\n";
    std::cout << "------------------------------------------------------------------------" << std::endl;
}

int main() {
    print_separator();
    std::cout << "        SINGLE-THREADED IN-PROCESS SYNTHETIC MICROBENCHMARK             " << std::endl;
    std::cout << "========================================================================" << std::endl;

    const int ITERATIONS = 5000000; // 5 Million ops per sub-test
    std::mt19937 rng(42); // Seeded for absolute execution determinism

    // Pre-generate random telemetry vectors to keep RNG math out of hot cycles
    std::vector<uint64_t> random_prices(ITERATIONS);
    std::vector<uint64_t> random_ids(ITERATIONS);
    std::vector<bool> random_sides(ITERATIONS);
    
    std::uniform_int_distribution<uint64_t> price_dist(10000, 900000); // Bounded safely inside array capacity
    std::uniform_int_distribution<uint64_t> id_dist(1, 4000000);
    std::uniform_int_distribution<int> side_dist(0, 1);

    for (int i = 0; i < ITERATIONS; ++i) {
        random_prices[i] = price_dist(rng);
        random_ids[i] = id_dist(rng);
        random_sides[i] = side_dist(rng) == 1;
    }

    // ========================================================================
    // BENCHMARK I: ZERO-ALLOCATION ARENA VS HEAP TRASHING
    // ========================================================================
    print_section("BENCHMARK I: MEMORY PIPELINE ALLOCATION EFFICIENCY");
    
    // Baseline: Heap thrashing simulation
    {
        auto start = high_resolution_clock::now();
        std::vector<Order*> heap_ptr_sink;
        heap_ptr_sink.reserve(100000);
        
        for (int i = 0; i < 100000; ++i) {
            Order* ord = new Order();
            ord->order_id = i;
            heap_ptr_sink.push_back(ord);
        }
        for (auto* ord : heap_ptr_sink) {
            delete ord;
        }
        auto end = high_resolution_clock::now();
        double heap_time = duration_cast<nanoseconds>(end - start).count() / 1e6;
        std::cout << "  [-] Standard OS Heap Allocation (100k New/Delete): " << heap_time << " ms" << std::endl;
    }

    // Arena Pool Verification
    {
        MemoryPool<Order> pool(1000000);
        std::vector<Order*> pool_ptr_sink;
        pool_ptr_sink.reserve(100000);

        auto start = high_resolution_clock::now();
        for (int i = 0; i < 100000; ++i) {
            Order* ord = pool.allocate();
            ord->order_id = i;
            pool_ptr_sink.push_back(ord);
        }
        for (auto* ord : pool_ptr_sink) {
            pool.deallocate(ord);
        }
        auto end = high_resolution_clock::now();
        double pool_time = duration_cast<nanoseconds>(end - start).count() / 1e6;
        std::cout << "  [+] Pre-allocated Arena Pool Allocation (100k Pops): " << pool_time << " ms" << std::endl;
    }

    // ========================================================================
    // BENCHMARK II: BITBOARD discovery (INTRINSICS VS TREE SEARCH)
    // ========================================================================
    print_section("BENCHMARK II: BITBOARD PRICE DISCOVERY INTELLIGENCE");
    {
        BitTree test_tree;
        // Seed the tree with initial sparse ticks
        for (int i = 0; i < 1000; ++i) {
            test_tree.set_bit(price_dist(rng));
        }

        auto start = high_resolution_clock::now();
        uint64_t dummy_checksum = 0;
        
        for (int i = 0; i < ITERATIONS; ++i) {
            // Simulate random order placement toggles
            uint64_t targeted_tick = random_prices[i];
            test_tree.set_bit(targeted_tick);
            
            // Invoke the hardware assembly step (MSB/LSB calls)
            dummy_checksum += test_tree.get_highest();
            dummy_checksum += test_tree.get_lowest();
            
            test_tree.clear_bit(targeted_tick);
        }
        
        auto end = high_resolution_clock::now();
        auto duration = duration_cast<nanoseconds>(end - start).count();
        double throughput = (static_cast<double>(ITERATIONS) / (duration / 1e9)) / 1e6;
        double latency = static_cast<double>(duration) / ITERATIONS;

        std::cout << "  [+] Compound Loop Iterations      : " << ITERATIONS << std::endl;
        std::cout << "  [+] Compound Loop Throughput      : " << throughput << " Million iterations/sec" << std::endl;
        std::cout << "  [+] Mean Compound Iteration Time  : " << latency << " ns / iteration" << std::endl;
        std::cout << "  [+] Hardware Checksum Validation  : " << dummy_checksum << " (Volatile Anti-Optimization Guard)" << std::endl;
    }

    // ========================================================================
    // BENCHMARK III: SYNTHETIC IN-PROCESS TICK UPDATE LOOP
    // ========================================================================
    print_section("BENCHMARK III: SYNTHETIC IN-PROCESS TICK UPDATES");
    {
        OrderBook engine;
        auto start = high_resolution_clock::now();
        uint64_t state_checksum = 0;

        for (int i = 0; i < ITERATIONS; ++i) {
            engine.inject_live_tick(random_prices[i], 500, random_sides[i]);
            state_checksum ^= engine.get_live_state_checksum() + static_cast<uint64_t>(i);
        }

        auto end = high_resolution_clock::now();
        auto duration = duration_cast<nanoseconds>(end - start).count();
        double throughput = (static_cast<double>(ITERATIONS) / (duration / 1e9)) / 1e6;
        double latency = static_cast<double>(duration) / ITERATIONS;

        std::cout << "  [+] Attempted Tick Updates      : " << ITERATIONS << " updates" << std::endl;
        std::cout << "  [+] In-Process Update Throughput: " << throughput << " Million updates/sec" << std::endl;
        std::cout << "  [+] Mean In-Process Loop Time   : " << latency << " ns / update" << std::endl;
        std::cout << "  [+] State Checksum              : " << state_checksum << std::endl;
    }

    // ========================================================================
    // BENCHMARK IV: MIXED IN-PROCESS ACTION LOOP
    // ========================================================================
    print_section("BENCHMARK IV: MIXED IN-PROCESS ENGINE ACTIONS");
    {
        OrderBook engine;
        
        // Phase A: Seed depth into the book to build resting queues
        for (int i = 0; i < 50000; ++i) {
            engine.process_order(i, price_dist(rng), 10, side_dist(rng));
        }

        auto start = high_resolution_clock::now();
        uint64_t dynamic_order_id = 100000;
        uint64_t attempted_crosses = 0;
        uint64_t successful_crosses = 0;
        uint64_t attempted_cancels = 0;
        uint64_t successful_cancels = 0;
        uint64_t accepted_orders = 0;
        uint64_t rejected_orders = 0;

        for (int i = 0; i < ITERATIONS; ++i) {
            uint64_t target_price = random_prices[i];
            int current_side = random_sides[i] ? 1 : 0;
            
            // Interleave Actions: 70% Adds, 20% Cancels, 10% Crossing Aggressive Fills
            if (i % 10 == 0) {
                // Force an aggressive cross by grabbing top of opposite book
                if (current_side == 0) {
                    int ask = engine.get_best_ask();
                    uint64_t crossing_price = (ask != -1) ? static_cast<uint64_t>(ask) : target_price + 5;
                    const ProcessResult result = engine.process_order(dynamic_order_id++, crossing_price, 5, 0);
                    successful_crosses += result.executed_quantity > 0;
                    accepted_orders += result.fully_accepted();
                    rejected_orders += !result.fully_accepted();
                } else {
                    int bid = engine.get_best_bid();
                    uint64_t crossing_price = (bid != -1) ? static_cast<uint64_t>(bid) : (target_price > 5 ? target_price - 5 : 1);
                    const ProcessResult result = engine.process_order(dynamic_order_id++, crossing_price, 5, 1);
                    successful_crosses += result.executed_quantity > 0;
                    accepted_orders += result.fully_accepted();
                    rejected_orders += !result.fully_accepted();
                }
                attempted_crosses++;
            } 
            else if (i % 5 == 0) {
                // Cancel previous order id bounds to test memory release stability
                uint64_t target_cancel_id = (dynamic_order_id > 20000) ? (dynamic_order_id - 15000) : 1;
                successful_cancels += engine.cancel_order(target_cancel_id);
                attempted_cancels++;
            } 
            else {
                // Post passive resting volume to the cache lines
                const ProcessResult result = engine.process_order(dynamic_order_id++, target_price, 15, current_side);
                accepted_orders += result.fully_accepted();
                rejected_orders += !result.fully_accepted();
            }
        }

        auto end = high_resolution_clock::now();
        auto duration = duration_cast<nanoseconds>(end - start).count();
        double throughput = (static_cast<double>(ITERATIONS) / (duration / 1e9)) / 1e6;
        double latency = static_cast<double>(duration) / ITERATIONS;

        std::cout << "  [+] Attempted Engine Actions   : " << ITERATIONS << " actions" << std::endl;
        std::cout << "  [+] Attempted Crossing Orders : " << attempted_crosses << std::endl;
        std::cout << "  [+] Crosses With >= 1 Fill    : " << successful_crosses << std::endl;
        std::cout << "  [+] Attempted Cancels         : " << attempted_cancels << std::endl;
        std::cout << "  [+] Successful Cancels        : " << successful_cancels << std::endl;
        std::cout << "  [+] Fully Accepted Orders     : " << accepted_orders << std::endl;
        std::cout << "  [+] Partially/Fully Rejected  : " << rejected_orders << std::endl;
        std::cout << "  [+] Final Active Orders       : " << engine.get_active_order_count() << std::endl;
        std::cout << "  [+] Full-Cycle Hot Throughput  : " << throughput << " Million actions/sec" << std::endl;
        std::cout << "  [+] Mean In-Process Loop Time  : " << latency << " ns / attempted action" << std::endl;
    }

    print_separator();
    std::cout << "  SEE engine_latency_benchmark FOR SEPARATE BATCH DISTRIBUTIONS        " << std::endl;
    print_separator();
    
    return 0;
}
