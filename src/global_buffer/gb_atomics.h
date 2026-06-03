#ifndef GB_ATOMICS_H
#define GB_ATOMICS_H
#include <stdint.h>
#include <string.h>
#include <stdatomic.h>

static inline uint64_t gb_load_u64(void *p) {
    return atomic_load_explicit((_Atomic uint64_t *)p, memory_order_acquire);
}
static inline void gb_store_u64(void *p, uint64_t v) {
    atomic_store_explicit((_Atomic uint64_t *)p, v, memory_order_release);
}
static inline uint32_t gb_load_u32(void *p) {
    return atomic_load_explicit((_Atomic uint32_t *)p, memory_order_acquire);
}
static inline void gb_store_u32(void *p, uint32_t v) {
    atomic_store_explicit((_Atomic uint32_t *)p, v, memory_order_release);
}
static inline void gb_memcpy(void *dst, const void *src, size_t n) {
    memcpy(dst, src, n);
}
#endif
