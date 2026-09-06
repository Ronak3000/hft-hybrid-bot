#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdlib>
#include <limits>
#include <memory>
#include <new>
#include <stdexcept>

#if defined(_MSC_VER) || defined(__MINGW32__)
#include <malloc.h>
#endif

// ============================================================================
// HARDWARE CACHE-ALIGNED MEMORY SLAB (64-Byte L1 Cache Line Aligned)
// ============================================================================
template <typename T>
class MemorySlab {
private:
    T* data_ptr = nullptr;
    size_t slab_capacity = 0;

public:
    explicit MemorySlab(size_t capacity) : slab_capacity(capacity) {
        if (capacity == 0 || capacity > std::numeric_limits<size_t>::max() / sizeof(T)) {
            throw std::invalid_argument("invalid memory slab capacity");
        }
        size_t bytes = capacity * sizeof(T);
        
        // Ensure total allocation is strictly aligned to 64-byte hardware cache lines
        if (bytes % 64 != 0) {
            bytes = ((bytes / 64) + 1) * 64;
        }

#if defined(_MSC_VER) || defined(__MINGW32__)
        data_ptr = static_cast<T*>(_aligned_malloc(bytes, 64));
#else
        data_ptr = static_cast<T*>(std::aligned_alloc(64, bytes));
#endif
        if (!data_ptr) throw std::bad_alloc();

        try {
            std::uninitialized_value_construct_n(data_ptr, slab_capacity);
        } catch (...) {
#if defined(_MSC_VER) || defined(__MINGW32__)
            _aligned_free(data_ptr);
#else
            std::free(data_ptr);
#endif
            data_ptr = nullptr;
            throw;
        }
    }

    MemorySlab(const MemorySlab&) = delete;
    MemorySlab& operator=(const MemorySlab&) = delete;

    ~MemorySlab() {
        if (data_ptr) {
            std::destroy_n(data_ptr, slab_capacity);
#if defined(_MSC_VER) || defined(__MINGW32__)
            _aligned_free(data_ptr);
#else
            std::free(data_ptr);
#endif
        }
    }

    // Small accessor intended to inline in optimized builds.
    inline T& operator[](size_t index) noexcept {
        return data_ptr[index];
    }

    inline const T& operator[](size_t index) const noexcept {
        return data_ptr[index];
    }

    inline void clear_all() {
        std::fill_n(data_ptr, slab_capacity, T{});
    }

    inline T* raw_data() noexcept { return data_ptr; }
    inline size_t capacity() const noexcept { return slab_capacity; }
};
