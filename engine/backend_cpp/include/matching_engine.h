#pragma once

#include <algorithm>
#include <array>
#include <bit>
#include <charconv>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "hardware_slab.h"
#include "memory_pool.h"
#include "order.h"

struct HistoricalMessage {
    uint64_t timestamp = 0;
    int type = 0;          // 1 = Add, 2 = Cancel, 3 = Execute
    uint64_t order_id = 0;
    int side = 0;          // 0 = Buy, 1 = Sell
    uint64_t price = 0;
    uint32_t qty = 0;
};

struct ASQuotes {
    double bid_price;
    double ask_price;
    double reservation_price;
};

enum class OrderStatus : uint8_t {
    ACCEPTED,
    INVALID_SIDE,
    INVALID_PRICE,
    INVALID_QUANTITY,
    INVALID_ORDER_ID,
    DUPLICATE_ORDER_ID,
    POOL_EXHAUSTED
};

struct Trade {
    uint64_t aggressor_order_id = 0;
    uint64_t resting_order_id = 0;
    uint64_t price = 0;
    uint32_t quantity = 0;
    Side aggressor_side = Side::BUY;
};

// Fixed-size and allocation-free so the normal order path stays lightweight.
struct ProcessResult {
    OrderStatus status = OrderStatus::ACCEPTED;
    uint32_t requested_quantity = 0;
    uint32_t executed_quantity = 0;
    uint32_t resting_quantity = 0;
    uint32_t rejected_quantity = 0;

    bool fully_accepted() const noexcept {
        return status == OrderStatus::ACCEPTED && rejected_quantity == 0;
    }

    bool quantity_is_conserved() const noexcept {
        return requested_quantity == executed_quantity + resting_quantity + rejected_quantity;
    }
};

enum class ExecutionStatus : uint8_t {
    EXECUTED,
    INVALID_ORDER_ID,
    INVALID_QUANTITY,
    ORDER_NOT_FOUND
};

struct ExecutionResult {
    ExecutionStatus status = ExecutionStatus::ORDER_NOT_FOUND;
    uint32_t requested_quantity = 0;
    uint32_t executed_quantity = 0;
    uint32_t unfilled_quantity = 0;
    uint32_t remaining_order_quantity = 0;
};

struct BitTree {
    static constexpr uint64_t MAX_PRICE_LEVELS = 1ULL << 20;

    uint64_t root = 0;
    std::array<uint64_t, 4> layer3{};
    std::array<uint64_t, 256> layer2{};
    std::array<uint64_t, 16384> layer1{};

    void set_bit(uint64_t idx) {
        validate_index(idx);
        const uint64_t l1_idx = idx / 64;
        const uint64_t l2_idx = l1_idx / 64;
        const uint64_t l3_idx = l2_idx / 64;

        layer1[l1_idx] |= 1ULL << (idx % 64);
        layer2[l2_idx] |= 1ULL << (l1_idx % 64);
        layer3[l3_idx] |= 1ULL << (l2_idx % 64);
        root |= 1ULL << l3_idx;
    }

    void clear_bit(uint64_t idx) {
        validate_index(idx);
        const uint64_t l1_idx = idx / 64;
        const uint64_t l2_idx = l1_idx / 64;
        const uint64_t l3_idx = l2_idx / 64;

        layer1[l1_idx] &= ~(1ULL << (idx % 64));
        if (layer1[l1_idx] == 0) {
            layer2[l2_idx] &= ~(1ULL << (l1_idx % 64));
            if (layer2[l2_idx] == 0) {
                layer3[l3_idx] &= ~(1ULL << (l2_idx % 64));
                if (layer3[l3_idx] == 0) root &= ~(1ULL << l3_idx);
            }
        }
    }

    int get_highest() const noexcept {
        if (root == 0) return -1;
        const uint64_t l3_idx = 63U - std::countl_zero(root);
        const uint64_t l2_idx = l3_idx * 64 + (63U - std::countl_zero(layer3[l3_idx]));
        const uint64_t l1_idx = l2_idx * 64 + (63U - std::countl_zero(layer2[l2_idx]));
        return static_cast<int>(l1_idx * 64 + (63U - std::countl_zero(layer1[l1_idx])));
    }

    int get_lowest() const noexcept {
        if (root == 0) return -1;
        const uint64_t l3_idx = std::countr_zero(root);
        const uint64_t l2_idx = l3_idx * 64 + std::countr_zero(layer3[l3_idx]);
        const uint64_t l1_idx = l2_idx * 64 + std::countr_zero(layer2[l2_idx]);
        return static_cast<int>(l1_idx * 64 + std::countr_zero(layer1[l1_idx]));
    }

private:
    static void validate_index(uint64_t idx) {
        if (idx >= MAX_PRICE_LEVELS) {
            throw std::out_of_range("bit-tree price index out of range");
        }
    }
};

class OrderBook {
private:
    struct NoopTradeSink {
        constexpr void operator()(const Trade&) const noexcept {}
    };

    static size_t validate_price_capacity(size_t capacity) {
        if (capacity > BitTree::MAX_PRICE_LEVELS) {
            throw std::invalid_argument("price capacity exceeds bit-tree range");
        }
        return capacity;
    }

    MemorySlab<PriceLevel> bids;
    MemorySlab<PriceLevel> asks;
    MemorySlab<Order*> active_orders;
    BitTree bids_tree;
    BitTree asks_tree;
    MemoryPool<Order> pool;

    std::vector<HistoricalMessage> history;
    size_t replay_index = 0;
    size_t active_order_count = 0;

    uint64_t live_ticker_price = 62500;
    uint64_t live_bid_depth_volume = 10;
    uint64_t live_ask_depth_volume = 10;
    bool mode_is_live = false;

    static bool parse_history_line(std::string_view line, HistoricalMessage& message) {
        std::array<std::string_view, 6> fields{};
        size_t start = 0;

        for (size_t index = 0; index < fields.size(); ++index) {
            const size_t comma = line.find(',', start);
            if (index + 1 == fields.size()) {
                if (comma != std::string_view::npos) return false;
                fields[index] = line.substr(start);
            } else {
                if (comma == std::string_view::npos) return false;
                fields[index] = line.substr(start, comma - start);
                start = comma + 1;
            }
        }

        auto parse_exact = [](std::string_view field, auto& value) {
            if (field.empty()) return false;
            const char* first = field.data();
            const char* last = first + field.size();
            const auto [parsed_to, error] = std::from_chars(first, last, value);
            return error == std::errc{} && parsed_to == last;
        };

        return parse_exact(fields[0], message.timestamp)
            && parse_exact(fields[1], message.type)
            && parse_exact(fields[2], message.order_id)
            && parse_exact(fields[3], message.side)
            && parse_exact(fields[4], message.price)
            && parse_exact(fields[5], message.qty);
    }

    void remove_filled_order(PriceLevel& level, BitTree& tree, Order* order) {
        const uint64_t price = order->price;
        active_orders[order->order_id] = nullptr;
        level.remove_order(order);
        pool.deallocate(order);
        --active_order_count;
        if (!level.head) tree.clear_bit(price);
    }

    template <typename TradeSink>
    void match_buy(
        uint64_t id,
        uint64_t limit_price,
        uint32_t& remaining,
        ProcessResult& result,
        TradeSink& on_trade) {
        while (remaining > 0) {
            const int best_ask = asks_tree.get_lowest();
            if (best_ask == -1 || static_cast<uint64_t>(best_ask) > limit_price) break;

            PriceLevel& level = asks[static_cast<size_t>(best_ask)];
            while (level.head != nullptr && remaining > 0) {
                Order* resting = level.head;
                const uint32_t matched = std::min(remaining, resting->quantity);
                on_trade(Trade{id, resting->order_id, resting->price, matched, Side::BUY});
                remaining -= matched;
                result.executed_quantity += matched;
                resting->quantity -= matched;
                level.total_volume -= matched;
                if (resting->quantity == 0) remove_filled_order(level, asks_tree, resting);
            }
        }
    }

    template <typename TradeSink>
    void match_sell(
        uint64_t id,
        uint64_t limit_price,
        uint32_t& remaining,
        ProcessResult& result,
        TradeSink& on_trade) {
        while (remaining > 0) {
            const int best_bid = bids_tree.get_highest();
            if (best_bid == -1 || static_cast<uint64_t>(best_bid) < limit_price) break;

            PriceLevel& level = bids[static_cast<size_t>(best_bid)];
            while (level.head != nullptr && remaining > 0) {
                Order* resting = level.head;
                const uint32_t matched = std::min(remaining, resting->quantity);
                on_trade(Trade{id, resting->order_id, resting->price, matched, Side::SELL});
                remaining -= matched;
                result.executed_quantity += matched;
                resting->quantity -= matched;
                level.total_volume -= matched;
                if (resting->quantity == 0) remove_filled_order(level, bids_tree, resting);
            }
        }
    }

public:
    explicit OrderBook(
        size_t price_level_capacity = 1'000'000,
        size_t order_pool_capacity = 1'000'000,
        size_t order_id_capacity = 5'000'000)
        : bids(validate_price_capacity(price_level_capacity)),
          asks(price_level_capacity),
          active_orders(order_id_capacity),
          pool(order_pool_capacity) {}

    // Aggregate trades drive paper-simulation signals only; they do not mutate the LOB.
    void inject_live_tick(uint64_t scaled_price, uint32_t volume, bool is_buyer_maker) noexcept {
        live_ticker_price = scaled_price;
        mode_is_live = true;
        if (is_buyer_maker) {
            live_bid_depth_volume = volume;
            live_ask_depth_volume = static_cast<uint64_t>(volume) * 2;
        } else {
            live_bid_depth_volume = static_cast<uint64_t>(volume) * 2;
            live_ask_depth_volume = volume;
        }
    }

    ProcessResult process_order(uint64_t id, uint64_t price, uint32_t qty, int side_value) {
        NoopTradeSink sink;
        return process_order_with_sink(id, price, qty, side_value, sink);
    }

    // The caller owns the sink. Tests and research logging can capture fills without
    // forcing allocations or virtual dispatch on the normal matching path.
    template <typename TradeSink>
    ProcessResult process_order_with_sink(
        uint64_t id,
        uint64_t price,
        uint32_t qty,
        int side_value,
        TradeSink&& on_trade) {
        ProcessResult result;
        result.requested_quantity = qty;

        if (side_value != static_cast<int>(Side::BUY) && side_value != static_cast<int>(Side::SELL)) {
            result.status = OrderStatus::INVALID_SIDE;
            result.rejected_quantity = qty;
            return result;
        }
        if (price == 0 || price >= bids.capacity()) {
            result.status = OrderStatus::INVALID_PRICE;
            result.rejected_quantity = qty;
            return result;
        }
        if (qty == 0) {
            result.status = OrderStatus::INVALID_QUANTITY;
            return result;
        }
        if (id >= active_orders.capacity()) {
            result.status = OrderStatus::INVALID_ORDER_ID;
            result.rejected_quantity = qty;
            return result;
        }
        if (active_orders[id] != nullptr) {
            result.status = OrderStatus::DUPLICATE_ORDER_ID;
            result.rejected_quantity = qty;
            return result;
        }

        const Side side = static_cast<Side>(side_value);
        uint32_t remaining = qty;
        if (side == Side::BUY) {
            match_buy(id, price, remaining, result, on_trade);
        } else {
            match_sell(id, price, remaining, result, on_trade);
        }

        if (remaining == 0) return result;

        Order* order = pool.allocate();
        if (order == nullptr) {
            result.status = OrderStatus::POOL_EXHAUSTED;
            result.rejected_quantity = remaining;
            return result;
        }

        order->order_id = id;
        order->price = price;
        order->quantity = remaining;
        order->side = side;

        PriceLevel& level = side == Side::BUY ? bids[price] : asks[price];
        BitTree& tree = side == Side::BUY ? bids_tree : asks_tree;
        level.push_back(order);
        tree.set_bit(price);
        active_orders[id] = order;
        ++active_order_count;
        result.resting_quantity = remaining;
        return result;
    }

    bool cancel_order(uint64_t id) {
        if (id >= active_orders.capacity()) return false;
        Order* order = active_orders[id];
        if (order == nullptr) return false;

        const uint64_t price = order->price;
        MemorySlab<PriceLevel>& book = order->side == Side::BUY ? bids : asks;
        BitTree& tree = order->side == Side::BUY ? bids_tree : asks_tree;
        PriceLevel& level = book[price];
        level.remove_order(order);
        active_orders[id] = nullptr;
        pool.deallocate(order);
        --active_order_count;
        if (!level.head) tree.clear_bit(price);
        return true;
    }

    ExecutionResult execute_order(uint64_t id, uint32_t qty) {
        ExecutionResult result;
        result.requested_quantity = qty;

        if (id >= active_orders.capacity()) {
            result.status = ExecutionStatus::INVALID_ORDER_ID;
            result.unfilled_quantity = qty;
            return result;
        }
        if (qty == 0) {
            result.status = ExecutionStatus::INVALID_QUANTITY;
            return result;
        }

        Order* order = active_orders[id];
        if (order == nullptr) {
            result.status = ExecutionStatus::ORDER_NOT_FOUND;
            result.unfilled_quantity = qty;
            return result;
        }

        MemorySlab<PriceLevel>& book = order->side == Side::BUY ? bids : asks;
        BitTree& tree = order->side == Side::BUY ? bids_tree : asks_tree;
        PriceLevel& level = book[order->price];
        const uint32_t executed = std::min(qty, order->quantity);
        order->quantity -= executed;
        level.total_volume -= executed;

        result.status = ExecutionStatus::EXECUTED;
        result.executed_quantity = executed;
        result.unfilled_quantity = qty - executed;
        result.remaining_order_quantity = order->quantity;
        if (order->quantity == 0) remove_filled_order(level, tree, order);
        return result;
    }

    int get_best_bid() const noexcept { return bids_tree.get_highest(); }
    int get_best_ask() const noexcept { return asks_tree.get_lowest(); }

    uint64_t get_best_bid_volume() const noexcept {
        const int price = get_best_bid();
        return price == -1 ? 0 : bids[static_cast<size_t>(price)].total_volume;
    }

    uint64_t get_best_ask_volume() const noexcept {
        const int price = get_best_ask();
        return price == -1 ? 0 : asks[static_cast<size_t>(price)].total_volume;
    }

    uint64_t get_level_volume(Side side, uint64_t price) const noexcept {
        if (price >= bids.capacity()) return 0;
        return side == Side::BUY ? bids[price].total_volume : asks[price].total_volume;
    }

    bool has_active_order(uint64_t id) const noexcept {
        return id < active_orders.capacity() && active_orders[id] != nullptr;
    }

    uint32_t get_order_quantity(uint64_t id) const noexcept {
        return has_active_order(id) ? active_orders[id]->quantity : 0;
    }

    size_t get_active_order_count() const noexcept { return active_order_count; }
    size_t get_pool_available() const noexcept { return pool.available(); }
    size_t get_pool_capacity() const noexcept { return pool.capacity(); }
    size_t get_history_size() const noexcept { return history.size(); }
    uint64_t get_live_state_checksum() const noexcept {
        return live_ticker_price ^ (live_bid_depth_volume << 1U) ^ (live_ask_depth_volume << 2U);
    }

    double get_obi() const noexcept {
        const double bid_volume = static_cast<double>(
            mode_is_live ? live_bid_depth_volume : get_best_bid_volume());
        const double ask_volume = static_cast<double>(
            mode_is_live ? live_ask_depth_volume : get_best_ask_volume());
        if (bid_volume + ask_volume == 0.0) return 0.0;
        return (bid_volume - ask_volume) / (bid_volume + ask_volume);
    }

    bool load_history_csv(const std::string& filepath) {
        std::ifstream file(filepath);
        if (!file.is_open()) return false;

        std::vector<HistoricalMessage> parsed_history;
        std::string line;
        bool first_nonempty_line = true;
        uint64_t previous_timestamp = 0;

        while (std::getline(file, line)) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            if (line.empty()) continue;

            HistoricalMessage message;
            if (!parse_history_line(line, message)) {
                const bool looks_like_header = std::any_of(
                    line.begin(), line.end(), [](unsigned char character) { return std::isalpha(character); });
                if (first_nonempty_line && looks_like_header) {
                    first_nonempty_line = false;
                    continue; // Optional header row.
                }
                return false;
            }
            first_nonempty_line = false;
            if (!parsed_history.empty() && message.timestamp < previous_timestamp) return false;
            if (message.type < 1 || message.type > 3) return false;
            if (message.order_id >= active_orders.capacity()) return false;
            if (message.type == 1
                && (message.side < 0 || message.side > 1 || message.price == 0
                    || message.price >= bids.capacity() || message.qty == 0)) return false;
            if (message.type == 3 && message.qty == 0) return false;
            previous_timestamp = message.timestamp;
            parsed_history.push_back(message);
        }

        if (parsed_history.empty()) return false;
        history = std::move(parsed_history);
        reset_cache();
        std::cout << "Engine history cache initialized: " << history.size() << " rows loaded.\n";
        return true;
    }

    uint64_t replay_next_tick() {
        if (replay_index >= history.size()) return 0;

        const uint64_t current_timestamp = history[replay_index].timestamp;
        while (replay_index < history.size() && history[replay_index].timestamp == current_timestamp) {
            const HistoricalMessage& message = history[replay_index];
            if (message.type == 1) process_order(message.order_id, message.price, message.qty, message.side);
            else if (message.type == 2) cancel_order(message.order_id);
            else execute_order(message.order_id, message.qty);
            ++replay_index;
        }
        return current_timestamp;
    }

    ASQuotes get_as_quotes(
        double mid_price,
        double inventory,
        double volatility,
        double gamma,
        double kappa,
        double rl_spread_multiplier) const {
        if (gamma <= 0.0 || kappa <= 0.0 || rl_spread_multiplier <= 0.0) {
            throw std::invalid_argument("quote parameters must be positive");
        }

        ASQuotes quotes;
        quotes.reservation_price = mid_price - inventory * gamma * std::pow(volatility, 2);
        double optimal_spread = gamma * std::pow(volatility, 2)
            + (2.0 / gamma) * std::log(1.0 + gamma / kappa);
        optimal_spread *= rl_spread_multiplier;
        quotes.bid_price = quotes.reservation_price - optimal_spread / 2.0;
        quotes.ask_price = quotes.reservation_price + optimal_spread / 2.0;
        return quotes;
    }

    void reset_cache() {
        replay_index = 0;
        active_order_count = 0;
        mode_is_live = false;
        bids_tree = BitTree{};
        asks_tree = BitTree{};
        active_orders.clear_all();
        bids.clear_all();
        asks.clear_all();
        pool.reset();
    }

    std::pair<double, bool> advance_tick() {
        if (mode_is_live) return {static_cast<double>(live_ticker_price), false};

        replay_next_tick();
        const bool is_out_of_data = replay_index >= history.size();
        double current_price = 62500.0;
        const int best_bid = get_best_bid();
        const int best_ask = get_best_ask();
        if (best_bid != -1 && best_ask != -1) current_price = (best_bid + best_ask) / 2.0;
        else if (best_bid != -1) current_price = best_bid;
        else if (best_ask != -1) current_price = best_ask;
        return {current_price, is_out_of_data};
    }
};
