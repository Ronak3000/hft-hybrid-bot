#pragma once
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <new>

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
        
        // Zero out physical memory block instantly
        std::memset(data_ptr, 0, bytes);
    }

    ~MemorySlab() {
        if (data_ptr) {
#if defined(_MSC_VER) || defined(__MINGW32__)
            _aligned_free(data_ptr);
#else
            std::free(data_ptr);
#endif
        }
    }

    // Force inline for bare-metal register offset indexing
    inline T& operator[](size_t index) noexcept {
        return data_ptr[index];
    }

    inline const T& operator[](size_t index) const noexcept {
        return data_ptr[index];
    }

    inline void clear_all() noexcept {
        std::memset(data_ptr, 0, slab_capacity * sizeof(T));
    }

    inline T* raw_data() noexcept { return data_ptr; }
    inline size_t capacity() const noexcept { return slab_capacity; }
};