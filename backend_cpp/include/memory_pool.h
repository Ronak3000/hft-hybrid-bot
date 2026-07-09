#pragma once
#include <vector>
#include "order.h"

template<typename T>
class MemoryPool {
private:
    std::vector<T> pool;           
    std::vector<T*> free_list;     
    size_t capacity;

public:
    MemoryPool(size_t size) : capacity(size) {
        pool.resize(capacity);
        free_list.reserve(capacity);

        for (size_t i = capacity; i > 0; --i) {
            free_list.push_back(&pool[i - 1]);
        }
    }

    T* allocate() {
        if (free_list.empty()) {
            return nullptr;
        }
        T* obj = free_list.back();
        free_list.pop_back();
        return obj;
    }

    void deallocate(T* obj) {
        if (obj != nullptr) {
            obj->reset(); 
            free_list.push_back(obj);
        }
    }

    size_t available() const {
        return free_list.size();
    }
};