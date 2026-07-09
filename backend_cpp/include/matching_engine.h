#pragma once
#include <vector>
#include <cmath>
#include <cstdint>
#include <string>
#include <algorithm>
#include <fstream>
#include <sstream>
#include <iostream>
#include <charconv>
#include <string_view>
#include "order.h"
#include "memory_pool.h"
#include "hardware_slab.h"

// ============================================================================
// 1. DATA STRUCTURES & BIT TREE
// ============================================================================
struct HistoricalMessage {
    uint64_t timestamp;
    int type;          // 1 = Add, 2 = Cancel, 3 = Execute
    uint64_t order_id;
    int side;          // 0 = Buy, 1 = Sell
    uint64_t price;
    uint32_t qty;
};

struct ASQuotes {
    double bid_price;
    double ask_price;
    double reservation_price;
};

// Hardware-level bitset tree for deterministic O(1) best bid/ask lookups
struct BitTree {
    uint64_t root = 0;
    uint64_t layer3[4] = {0};
    uint64_t layer2[256] = {0};
    uint64_t layer1[16384] = {0};

    void set_bit(uint64_t idx) {
        uint64_t l1_idx = idx / 64;
        uint64_t l2_idx = l1_idx / 64;
        uint64_t l3_idx = l2_idx / 64;

        layer1[l1_idx] |= (1ULL << (idx % 64));
        layer2[l2_idx] |= (1ULL << (l1_idx % 64));
        layer3[l3_idx] |= (1ULL << (l2_idx % 64));
        root |= (1ULL << (l3_idx % 64));
    }

    void clear_bit(uint64_t idx) {
        uint64_t l1_idx = idx / 64;
        uint64_t l2_idx = l1_idx / 64;
        uint64_t l3_idx = l2_idx / 64;

        layer1[l1_idx] &= ~(1ULL << (idx % 64));
        if (layer1[l1_idx] == 0) {
            layer2[l2_idx] &= ~(1ULL << (l1_idx % 64));
            if (layer2[l2_idx] == 0) {
                layer3[l3_idx] &= ~(1ULL << (l2_idx % 64));
                if (layer3[l3_idx] == 0) root &= ~(1ULL << (l3_idx % 64));
            }
        }
    }

    int get_highest() const {
        if (root == 0) return -1;
        uint64_t l3_idx = 63 - __builtin_clzll(root);
        uint64_t l2_idx = (l3_idx * 64) + (63 - __builtin_clzll(layer3[l3_idx]));
        uint64_t l1_idx = (l2_idx * 64) + (63 - __builtin_clzll(layer2[l2_idx]));
        return (l1_idx * 64) + (63 - __builtin_clzll(layer1[l1_idx]));
    }

    int get_lowest() const {
        if (root == 0) return -1;
        uint64_t l3_idx = __builtin_ctzll(root);
        uint64_t l2_idx = (l3_idx * 64) + __builtin_ctzll(layer3[l3_idx]);
        uint64_t l1_idx = (l2_idx * 64) + __builtin_ctzll(layer2[l2_idx]);
        return (l1_idx * 64) + __builtin_ctzll(layer1[l1_idx]);
    }
};

// ============================================================================
// 2. CORE MATCHING ENGINE
// ============================================================================
class OrderBook {
private:
    // Powered by your hardware_slab.h template
    MemorySlab<PriceLevel> bids;
    MemorySlab<PriceLevel> asks;
    MemorySlab<Order*> active_orders; // Direct O(1) array index lookup by Order ID
    
    BitTree bids_tree;
    BitTree asks_tree;
    MemoryPool<Order> pool;

    std::vector<HistoricalMessage> history;
    size_t replay_index = 0;

public:
    // Pre-allocate continuous physical slabs (up to 1M prices, 5M active order IDs)
    OrderBook() 
        : bids(1000000), 
          asks(1000000), 
          active_orders(5000000), 
          pool(1000000) {
    }

    std::string process_order(uint64_t id, uint64_t price, uint32_t qty, int side_val) {
        Side side = static_cast<Side>(side_val);
        uint32_t remaining_qty = qty;

        if (side == Side::BUY) {
            while (remaining_qty > 0) {
                int best_ask = asks_tree.get_lowest();
                if (best_ask == -1 || (uint64_t)best_ask > price) break;

                PriceLevel& level = asks[best_ask];
                while (level.head && remaining_qty > 0) {
                    Order* resting = level.head;
                    uint32_t match_qty = std::min(remaining_qty, resting->quantity);
                    
                    remaining_qty -= match_qty;
                    resting->quantity -= match_qty;
                    level.total_volume -= match_qty;

                    if (resting->quantity == 0) {
                        if (resting->order_id < active_orders.capacity()) {
                            active_orders[resting->order_id] = nullptr;
                        }
                        level.remove_order(resting);
                        pool.deallocate(resting);
                    }
                }
                if (!level.head) asks_tree.clear_bit(best_ask);
            }

            if (remaining_qty > 0) {
                Order* order = pool.allocate();
                if (!order) return "Pool Exhausted";
                order->order_id = id;
                order->price = price;
                order->quantity = remaining_qty;
                order->side = side;

                bids[price].push_back(order);
                bids_tree.set_bit(price);
                
                // Write directly to Cache-Aligned Slab index (~1ns)
                if (id < active_orders.capacity()) {
                    active_orders[id] = order;
                }
            }
        } else {
            while (remaining_qty > 0) {
                int best_bid = bids_tree.get_highest();
                if (best_bid == -1 || (uint64_t)best_bid < price) break;

                PriceLevel& level = bids[best_bid];
                while (level.head && remaining_qty > 0) {
                    Order* resting = level.head;
                    uint32_t match_qty = std::min(remaining_qty, resting->quantity);
                    
                    remaining_qty -= match_qty;
                    resting->quantity -= match_qty;
                    level.total_volume -= match_qty;

                    if (resting->quantity == 0) {
                        if (resting->order_id < active_orders.capacity()) {
                            active_orders[resting->order_id] = nullptr;
                        }
                        level.remove_order(resting);
                        pool.deallocate(resting);
                    }
                }
                if (!level.head) bids_tree.clear_bit(best_bid);
            }

            if (remaining_qty > 0) {
                Order* order = pool.allocate();
                if (!order) return "Pool Exhausted";
                order->order_id = id;
                order->price = price;
                order->quantity = remaining_qty;
                order->side = side;

                asks[price].push_back(order);
                asks_tree.set_bit(price);
                
                if (id < active_orders.capacity()) {
                    active_orders[id] = order;
                }
            }
        }
        return "Order Processed";
    }

    bool cancel_order(uint64_t id) {
        // Direct Hardware Register Indexing (~1ns, zero hashing overhead)
        if (id >= active_orders.capacity()) return false;
        Order* order = active_orders[id];
        if (!order) return false;

        uint64_t price = order->price;
        Side side = order->side;

        MemorySlab<PriceLevel>& book = (side == Side::BUY) ? bids : asks;
        BitTree& tree = (side == Side::BUY) ? bids_tree : asks_tree;
        PriceLevel& level = book[price];

        level.remove_order(order);
        pool.deallocate(order);
        active_orders[id] = nullptr; // Clear slab index

        if (!level.head) tree.clear_bit(price);
        return true;
    }

    int get_best_bid() const { return bids_tree.get_highest(); }
    int get_best_ask() const { return asks_tree.get_lowest(); }

    uint32_t get_best_bid_volume() const {
        int best_bid = get_best_bid();
        return (best_bid == -1) ? 0 : bids[best_bid].total_volume;
    }

    uint32_t get_best_ask_volume() const {
        int best_ask = get_best_ask();
        return (best_ask == -1) ? 0 : asks[best_ask].total_volume;
    }

    // --- Hardware-Calculated Microstructure Signal ---
    double get_obi() const {
        double v_bid = static_cast<double>(get_best_bid_volume());
        double v_ask = static_cast<double>(get_best_ask_volume());
        if (v_bid + v_ask == 0.0) return 0.0;
        return (v_bid - v_ask) / (v_bid + v_ask);
    }

    // --- Ultra-Optimized Zero-Allocation CSV Loader ---
    bool load_history_csv(const std::string& filepath) {
        std::ifstream file(filepath, std::ios::binary | std::ios::ate);
        if (!file.is_open()) return false;

        std::streamsize size = file.tellg();
        file.seekg(0, std::ios::beg);

        std::string buffer(size, '\0');
        if (!file.read(&buffer[0], size)) return false;

        history.clear();
        replay_index = 0;
        history.reserve(size / 40); 

        const char* ptr = buffer.data();
        const char* end = buffer.data() + size;

        while (ptr < end && *ptr != '\n') ptr++;
        if (ptr < end) ptr++;

        while (ptr < end) {
            if (*ptr == '\n' || *ptr == '\r') {
                ptr++; continue;
            }
            HistoricalMessage msg;
            auto parse_field = [&](auto& field, char separator) {
                auto [p, ec] = std::from_chars(ptr, end, field);
                if (ec == std::errc{}) {
                    ptr = p;
                    if (ptr < end && *ptr == separator) ptr++;
                }
            };

            parse_field(msg.timestamp, ',');
            parse_field(msg.type, ',');
            parse_field(msg.order_id, ',');
            parse_field(msg.side, ',');
            parse_field(msg.price, ',');
            parse_field(msg.qty, '\n');

            history.push_back(msg);
        }
        std::cout << "Engine RAM Cache Initialized: " << history.size() << " rows loaded." << std::endl;
        return true;
    }

    uint64_t replay_next_tick() {
        if (replay_index >= history.size()) return 0;

        uint64_t current_timestamp = history[replay_index].timestamp;
        while (replay_index < history.size() && history[replay_index].timestamp == current_timestamp) {
            const HistoricalMessage& msg = history[replay_index];

            if (msg.type == 1) { 
                process_order(msg.order_id, msg.price, msg.qty, msg.side);
            } 
            else if (msg.type == 2 || msg.type == 3) { 
                cancel_order(msg.order_id); 
            }
            replay_index++;
        }
        return current_timestamp;
    }

    // --- Mathematical Oracle ---
    ASQuotes get_as_quotes(double mid_price, double inventory, double volatility, double gamma, double kappa, double rl_spread_multiplier) {
        ASQuotes quotes;
        quotes.reservation_price = mid_price - (inventory * gamma * std::pow(volatility, 2));

        double optimal_spread = (gamma * std::pow(volatility, 2)) + 
                                (2.0 / gamma) * std::log(1.0 + (gamma / kappa));

        optimal_spread *= rl_spread_multiplier;

        quotes.bid_price = quotes.reservation_price - (optimal_spread / 2.0);
        quotes.ask_price = quotes.reservation_price + (optimal_spread / 2.0);
        
        return quotes;
    }

    // --- Python RL Bridges ---
    void reset_cache() {
        replay_index = 0;
        bids_tree = BitTree();
        asks_tree = BitTree();
        // Instant hardware memory wipe via memset (Zero iteration overhead)
        active_orders.clear_all();
        bids.clear_all();
        asks.clear_all();
    }

    std::pair<double, bool> advance_tick() {
        replay_next_tick();
        bool is_out_of_data = (replay_index >= history.size());
        
        double current_price = 62500.0; 
        int best_bid = get_best_bid();
        int best_ask = get_best_ask();
        
        if (best_bid != -1 && best_ask != -1) current_price = (best_bid + best_ask) / 2.0;
        else if (best_bid != -1) current_price = best_bid;
        else if (best_ask != -1) current_price = best_ask;
        
        return std::make_pair(current_price, is_out_of_data);
    }
};