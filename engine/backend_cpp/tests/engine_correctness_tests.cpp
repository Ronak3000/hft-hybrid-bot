#include <cstdio>
#include <deque>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

#include "matching_engine.h"

namespace {

class TestFailure : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            throw TestFailure(std::string("CHECK failed: ") + #condition \
                + " at line " + std::to_string(__LINE__)); \
        } \
    } while (false)

using Test = std::pair<const char*, std::function<void()>>;

OrderBook small_book(size_t pool_capacity = 16) {
    return OrderBook(1'000, pool_capacity, 1'000);
}

class ReferenceBook {
private:
    struct ReferenceOrder {
        uint64_t id;
        uint32_t quantity;
    };

    std::map<uint64_t, std::deque<ReferenceOrder>, std::greater<>> bids;
    std::map<uint64_t, std::deque<ReferenceOrder>> asks;
    std::unordered_set<uint64_t> active_ids;

public:
    ProcessResult process(
        uint64_t id,
        uint64_t price,
        uint32_t quantity,
        Side side,
        std::vector<Trade>& trades) {
        ProcessResult result;
        result.requested_quantity = quantity;
        if (active_ids.contains(id)) {
            result.status = OrderStatus::DUPLICATE_ORDER_ID;
            result.rejected_quantity = quantity;
            return result;
        }

        uint32_t remaining = quantity;
        if (side == Side::BUY) {
            while (remaining > 0 && !asks.empty() && asks.begin()->first <= price) {
                auto level = asks.begin();
                auto& queue = level->second;
                while (remaining > 0 && !queue.empty()) {
                    auto& resting = queue.front();
                    const uint32_t matched = std::min(remaining, resting.quantity);
                    trades.push_back({id, resting.id, level->first, matched, side});
                    remaining -= matched;
                    resting.quantity -= matched;
                    result.executed_quantity += matched;
                    if (resting.quantity == 0) {
                        active_ids.erase(resting.id);
                        queue.pop_front();
                    }
                }
                if (queue.empty()) asks.erase(level);
            }
            if (remaining > 0) bids[price].push_back({id, remaining});
        } else {
            while (remaining > 0 && !bids.empty() && bids.begin()->first >= price) {
                auto level = bids.begin();
                auto& queue = level->second;
                while (remaining > 0 && !queue.empty()) {
                    auto& resting = queue.front();
                    const uint32_t matched = std::min(remaining, resting.quantity);
                    trades.push_back({id, resting.id, level->first, matched, side});
                    remaining -= matched;
                    resting.quantity -= matched;
                    result.executed_quantity += matched;
                    if (resting.quantity == 0) {
                        active_ids.erase(resting.id);
                        queue.pop_front();
                    }
                }
                if (queue.empty()) bids.erase(level);
            }
            if (remaining > 0) asks[price].push_back({id, remaining});
        }

        if (remaining > 0) {
            active_ids.insert(id);
            result.resting_quantity = remaining;
        }
        return result;
    }

    bool cancel(uint64_t id) {
        auto cancel_from = [id](auto& levels) {
            for (auto level = levels.begin(); level != levels.end(); ++level) {
                auto& queue = level->second;
                for (auto order = queue.begin(); order != queue.end(); ++order) {
                    if (order->id != id) continue;
                    queue.erase(order);
                    if (queue.empty()) levels.erase(level);
                    return true;
                }
            }
            return false;
        };

        if (!active_ids.contains(id)) return false;
        const bool removed = cancel_from(bids) || cancel_from(asks);
        if (removed) active_ids.erase(id);
        return removed;
    }

    int best_bid() const { return bids.empty() ? -1 : static_cast<int>(bids.begin()->first); }
    int best_ask() const { return asks.empty() ? -1 : static_cast<int>(asks.begin()->first); }
    size_t active_count() const { return active_ids.size(); }

    uint64_t best_bid_volume() const {
        if (bids.empty()) return 0;
        uint64_t volume = 0;
        for (const auto& order : bids.begin()->second) volume += order.quantity;
        return volume;
    }

    uint64_t best_ask_volume() const {
        if (asks.empty()) return 0;
        uint64_t volume = 0;
        for (const auto& order : asks.begin()->second) volume += order.quantity;
        return volume;
    }
};

void test_rejects_invalid_input_without_mutation() {
    auto book = small_book();

    const auto invalid_side = book.process_order(1, 100, 5, 2);
    CHECK(invalid_side.status == OrderStatus::INVALID_SIDE);
    CHECK(invalid_side.rejected_quantity == 5);
    CHECK(invalid_side.quantity_is_conserved());

    const auto invalid_price_zero = book.process_order(1, 0, 5, 0);
    CHECK(invalid_price_zero.status == OrderStatus::INVALID_PRICE);
    CHECK(invalid_price_zero.quantity_is_conserved());

    const auto invalid_price_high = book.process_order(1, 1'000, 5, 0);
    CHECK(invalid_price_high.status == OrderStatus::INVALID_PRICE);
    CHECK(invalid_price_high.quantity_is_conserved());

    const auto invalid_quantity = book.process_order(1, 100, 0, 0);
    CHECK(invalid_quantity.status == OrderStatus::INVALID_QUANTITY);
    CHECK(invalid_quantity.quantity_is_conserved());

    const auto invalid_id = book.process_order(1'000, 100, 5, 0);
    CHECK(invalid_id.status == OrderStatus::INVALID_ORDER_ID);
    CHECK(invalid_id.quantity_is_conserved());

    CHECK(book.get_active_order_count() == 0);
    CHECK(book.get_pool_available() == book.get_pool_capacity());
    CHECK(book.get_best_bid() == -1);
    CHECK(book.get_best_ask() == -1);
}

void test_duplicate_id_preserves_original_order() {
    auto book = small_book();
    CHECK(book.process_order(7, 100, 5, 0).fully_accepted());

    const auto duplicate = book.process_order(7, 101, 9, 0);
    CHECK(duplicate.status == OrderStatus::DUPLICATE_ORDER_ID);
    CHECK(duplicate.rejected_quantity == 9);
    CHECK(duplicate.quantity_is_conserved());
    CHECK(book.get_order_quantity(7) == 5);
    CHECK(book.get_level_volume(Side::BUY, 100) == 5);
    CHECK(book.get_level_volume(Side::BUY, 101) == 0);
    CHECK(book.get_active_order_count() == 1);
}

void test_fifo_and_partial_fill() {
    auto book = small_book();
    CHECK(book.process_order(1, 100, 5, 1).fully_accepted());
    CHECK(book.process_order(2, 100, 7, 1).fully_accepted());

    std::vector<Trade> trades;
    const auto result = book.process_order_with_sink(
        3, 100, 8, 0, [&trades](const Trade& trade) { trades.push_back(trade); });

    CHECK(result.fully_accepted());
    CHECK(result.executed_quantity == 8);
    CHECK(result.resting_quantity == 0);
    CHECK(result.quantity_is_conserved());
    CHECK(trades.size() == 2);
    CHECK(trades[0].resting_order_id == 1);
    CHECK(trades[0].quantity == 5);
    CHECK(trades[1].resting_order_id == 2);
    CHECK(trades[1].quantity == 3);
    CHECK(!book.has_active_order(1));
    CHECK(book.get_order_quantity(2) == 4);
    CHECK(book.get_best_ask_volume() == 4);
}

void test_price_priority_and_resting_price() {
    auto book = small_book();
    CHECK(book.process_order(1, 101, 4, 1).fully_accepted());
    CHECK(book.process_order(2, 100, 3, 1).fully_accepted());

    std::vector<Trade> trades;
    const auto result = book.process_order_with_sink(
        3, 101, 6, 0, [&trades](const Trade& trade) { trades.push_back(trade); });

    CHECK(result.executed_quantity == 6);
    CHECK(result.quantity_is_conserved());
    CHECK(trades.size() == 2);
    CHECK(trades[0].resting_order_id == 2);
    CHECK(trades[0].price == 100);
    CHECK(trades[1].resting_order_id == 1);
    CHECK(trades[1].price == 101);
    CHECK(book.get_order_quantity(1) == 1);
}

void test_cancel_middle_keeps_fifo_links_valid() {
    auto book = small_book();
    CHECK(book.process_order(10, 100, 2, 0).fully_accepted());
    CHECK(book.process_order(11, 100, 2, 0).fully_accepted());
    CHECK(book.process_order(12, 100, 2, 0).fully_accepted());
    CHECK(book.cancel_order(11));
    CHECK(!book.cancel_order(11));
    CHECK(book.get_best_bid_volume() == 4);

    std::vector<Trade> trades;
    const auto result = book.process_order_with_sink(
        20, 100, 4, 1, [&trades](const Trade& trade) { trades.push_back(trade); });
    CHECK(result.executed_quantity == 4);
    CHECK(trades.size() == 2);
    CHECK(trades[0].resting_order_id == 10);
    CHECK(trades[1].resting_order_id == 12);
    CHECK(book.get_best_bid() == -1);
    CHECK(book.get_active_order_count() == 0);
}

void test_pool_exhaustion_is_explicit_and_recoverable() {
    auto book = small_book(2);
    CHECK(book.process_order(1, 100, 1, 0).fully_accepted());
    CHECK(book.process_order(2, 99, 1, 0).fully_accepted());

    const auto exhausted = book.process_order(3, 98, 4, 0);
    CHECK(exhausted.status == OrderStatus::POOL_EXHAUSTED);
    CHECK(exhausted.rejected_quantity == 4);
    CHECK(exhausted.quantity_is_conserved());
    CHECK(!book.has_active_order(3));

    CHECK(book.cancel_order(1));
    CHECK(book.process_order(3, 98, 4, 0).fully_accepted());
    CHECK(book.has_active_order(3));
}

void test_reset_restores_pool_and_book_state() {
    auto book = small_book(2);
    CHECK(book.process_order(1, 100, 1, 0).fully_accepted());
    CHECK(book.process_order(2, 101, 1, 1).fully_accepted());
    CHECK(book.get_pool_available() == 0);

    book.reset_cache();
    CHECK(book.get_pool_available() == 2);
    CHECK(book.get_active_order_count() == 0);
    CHECK(book.get_best_bid() == -1);
    CHECK(book.get_best_ask() == -1);
    CHECK(!book.has_active_order(1));
    CHECK(book.process_order(1, 100, 2, 0).fully_accepted());
}

void test_execution_is_partial_not_cancel() {
    auto book = small_book();
    CHECK(book.process_order(5, 100, 10, 0).fully_accepted());

    const auto partial = book.execute_order(5, 4);
    CHECK(partial.status == ExecutionStatus::EXECUTED);
    CHECK(partial.executed_quantity == 4);
    CHECK(partial.remaining_order_quantity == 6);
    CHECK(book.get_order_quantity(5) == 6);
    CHECK(book.get_best_bid_volume() == 6);

    const auto remainder = book.execute_order(5, 10);
    CHECK(remainder.status == ExecutionStatus::EXECUTED);
    CHECK(remainder.executed_quantity == 6);
    CHECK(remainder.unfilled_quantity == 4);
    CHECK(remainder.remaining_order_quantity == 0);
    CHECK(!book.has_active_order(5));
    CHECK(book.get_best_bid() == -1);
}

void test_book_never_remains_crossed() {
    auto book = small_book();
    CHECK(book.process_order(1, 100, 5, 0).fully_accepted());
    const auto sell = book.process_order(2, 99, 7, 1);
    CHECK(sell.executed_quantity == 5);
    CHECK(sell.resting_quantity == 2);
    CHECK(sell.quantity_is_conserved());
    CHECK(book.get_best_bid() == -1);
    CHECK(book.get_best_ask() == 99);
}

void test_headerless_history_keeps_first_row_and_replays_partial_execution() {
    const std::string path = "engine_history_test.csv";
    {
        std::ofstream file(path);
        file << "1000,1,1,0,100,10\n";
        file << "1001,3,1,0,100,4\n";
    }

    auto book = small_book();
    CHECK(book.load_history_csv(path));
    CHECK(book.get_history_size() == 2);
    CHECK(book.replay_next_tick() == 1000);
    CHECK(book.get_order_quantity(1) == 10);
    CHECK(book.replay_next_tick() == 1001);
    CHECK(book.get_order_quantity(1) == 6);
    std::remove(path.c_str());
}

void test_history_accepts_header_and_rejects_malformed_data() {
    const std::string header_path = "engine_history_header_test.csv";
    {
        std::ofstream file(header_path);
        file << "timestamp,type,order_id,side,price,qty\n";
        file << "1000,1,1,1,101,3\n";
    }
    auto book = small_book();
    CHECK(book.load_history_csv(header_path));
    CHECK(book.get_history_size() == 1);
    CHECK(book.replay_next_tick() == 1000);
    CHECK(book.get_order_quantity(1) == 3);
    std::remove(header_path.c_str());

    const std::string malformed_path = "engine_history_malformed_test.csv";
    {
        std::ofstream file(malformed_path);
        file << "1000,1,broken,0,100,10\n";
    }
    CHECK(!book.load_history_csv(malformed_path));
    std::remove(malformed_path.c_str());
}

void test_bit_tree_boundaries() {
    BitTree tree;
    tree.set_bit(0);
    tree.set_bit(BitTree::MAX_PRICE_LEVELS - 1);
    CHECK(tree.get_lowest() == 0);
    CHECK(tree.get_highest() == static_cast<int>(BitTree::MAX_PRICE_LEVELS - 1));
    tree.clear_bit(0);
    tree.clear_bit(BitTree::MAX_PRICE_LEVELS - 1);
    CHECK(tree.get_lowest() == -1);
    CHECK(tree.get_highest() == -1);

    bool threw = false;
    try {
        tree.set_bit(BitTree::MAX_PRICE_LEVELS);
    } catch (const std::out_of_range&) {
        threw = true;
    }
    CHECK(threw);
}

void test_randomized_operations_match_reference_book() {
    OrderBook book(1'000, 5'000, 10'000);
    ReferenceBook reference;
    std::mt19937 random(42);
    std::uniform_int_distribution<uint64_t> price_distribution(95, 105);
    std::uniform_int_distribution<uint32_t> quantity_distribution(1, 10);
    std::uniform_int_distribution<int> side_distribution(0, 1);
    std::uniform_int_distribution<int> action_distribution(0, 99);
    uint64_t next_id = 1;

    for (size_t step = 0; step < 5'000; ++step) {
        if (action_distribution(random) < 80) {
            const uint64_t id = next_id++;
            const uint64_t price = price_distribution(random);
            const uint32_t quantity = quantity_distribution(random);
            const Side side = static_cast<Side>(side_distribution(random));
            std::vector<Trade> actual_trades;
            std::vector<Trade> expected_trades;

            const auto actual = book.process_order_with_sink(
                id,
                price,
                quantity,
                static_cast<int>(side),
                [&actual_trades](const Trade& trade) { actual_trades.push_back(trade); });
            const auto expected = reference.process(id, price, quantity, side, expected_trades);

            CHECK(actual.status == expected.status);
            CHECK(actual.executed_quantity == expected.executed_quantity);
            CHECK(actual.resting_quantity == expected.resting_quantity);
            CHECK(actual.rejected_quantity == expected.rejected_quantity);
            CHECK(actual.quantity_is_conserved());
            CHECK(actual_trades.size() == expected_trades.size());
            for (size_t index = 0; index < actual_trades.size(); ++index) {
                CHECK(actual_trades[index].aggressor_order_id == expected_trades[index].aggressor_order_id);
                CHECK(actual_trades[index].resting_order_id == expected_trades[index].resting_order_id);
                CHECK(actual_trades[index].price == expected_trades[index].price);
                CHECK(actual_trades[index].quantity == expected_trades[index].quantity);
                CHECK(actual_trades[index].aggressor_side == expected_trades[index].aggressor_side);
            }
        } else {
            const uint64_t candidate = next_id == 1 ? 1 : random() % next_id;
            CHECK(book.cancel_order(candidate) == reference.cancel(candidate));
        }

        CHECK(book.get_best_bid() == reference.best_bid());
        CHECK(book.get_best_ask() == reference.best_ask());
        CHECK(book.get_best_bid_volume() == reference.best_bid_volume());
        CHECK(book.get_best_ask_volume() == reference.best_ask_volume());
        CHECK(book.get_active_order_count() == reference.active_count());
    }
}

} // namespace

int main() {
    std::cout << std::unitbuf;
    std::cerr << std::unitbuf;
    const std::vector<Test> tests = {
        {"invalid input is rejected without mutation", test_rejects_invalid_input_without_mutation},
        {"duplicate IDs preserve the original", test_duplicate_id_preserves_original_order},
        {"FIFO and partial fills", test_fifo_and_partial_fill},
        {"price priority and resting-price execution", test_price_priority_and_resting_price},
        {"middle cancellation preserves links", test_cancel_middle_keeps_fifo_links_valid},
        {"pool exhaustion is explicit and recoverable", test_pool_exhaustion_is_explicit_and_recoverable},
        {"reset restores pool and state", test_reset_restores_pool_and_book_state},
        {"execution is partial rather than cancellation", test_execution_is_partial_not_cancel},
        {"book does not remain crossed", test_book_never_remains_crossed},
        {"headerless history keeps first row", test_headerless_history_keeps_first_row_and_replays_partial_execution},
        {"history header and malformed-row handling", test_history_accepts_header_and_rejects_malformed_data},
        {"bit-tree boundaries", test_bit_tree_boundaries},
        {"randomized operations match a reference book", test_randomized_operations_match_reference_book},
    };

    size_t passed = 0;
    for (const auto& [name, test] : tests) {
        try {
            test();
            ++passed;
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception& error) {
            std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }

    std::cout << passed << '/' << tests.size() << " tests passed\n";
    return passed == tests.size() ? 0 : 1;
}
