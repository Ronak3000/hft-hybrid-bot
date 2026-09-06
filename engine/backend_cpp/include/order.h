#pragma once
#include <cassert>
#include <cstdint>

enum class Side : uint8_t {
    BUY = 0,
    SELL = 1
};

struct Order {
    uint64_t order_id;
    uint64_t price;     
    uint32_t quantity;
    Side side;

    Order* next = nullptr;
    Order* prev = nullptr;

    void reset() {
        order_id = 0; price = 0; quantity = 0;
        side = Side::BUY;
        next = nullptr; prev = nullptr;
    }
};

struct PriceLevel {
    Order* head = nullptr;
    Order* tail = nullptr;
    uint64_t total_volume = 0;

    void push_back(Order* order) {
        if (!head) {
            head = tail = order;
        } else {
            tail->next = order;
            order->prev = tail;
            tail = order;
        }
        // Event 1: Adding an Order
        total_volume += order->quantity;
    }

    void remove_order(Order* order) {
        assert(order != nullptr && order->quantity <= total_volume);
        total_volume -= order->quantity; 
        
        if (order->prev) order->prev->next = order->next;
        if (order->next) order->next->prev = order->prev;
        if (head == order) head = order->next;
        if (tail == order) tail = order->prev;
        
        order->prev = nullptr;
        order->next = nullptr;
    }
};
