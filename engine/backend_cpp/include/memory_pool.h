#pragma once
#include <cstddef>
#include <vector>

template<typename T>
class MemoryPool {
private:
    std::vector<T> pool;           
    std::vector<T*> free_list;     
public:
    explicit MemoryPool(size_t size) : pool(size) {
        free_list.reserve(size);
        reset();
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

    size_t capacity() const {
        return pool.size();
    }

    void reset() {
        free_list.clear();
        for (auto& object : pool) {
            object.reset();
        }
        for (size_t i = pool.size(); i > 0; --i) {
            free_list.push_back(&pool[i - 1]);
        }
    }
};
