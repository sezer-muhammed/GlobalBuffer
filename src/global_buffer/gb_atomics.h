#ifndef GB_ATOMICS_H
#define GB_ATOMICS_H
#include <stdint.h>
#include <string.h>

#ifdef _MSC_VER
/*
 * MSVC's <stdatomic.h> only works with clang-cl, not the native compiler.
 * On x64 Windows the CPU provides TSO, so volatile + a compiler fence gives
 * acquire-load / release-store without extra hardware instructions.
 */
#include <intrin.h>
#pragma intrinsic(_ReadWriteBarrier)

static inline uint64_t gb_load_u64(void *p) {
    _ReadWriteBarrier();
    uint64_t v = *(volatile uint64_t *)p;
    _ReadWriteBarrier();
    return v;
}
static inline void gb_store_u64(void *p, uint64_t v) {
    _ReadWriteBarrier();
    *(volatile uint64_t *)p = v;
    _ReadWriteBarrier();
}
static inline uint32_t gb_load_u32(void *p) {
    _ReadWriteBarrier();
    uint32_t v = *(volatile uint32_t *)p;
    _ReadWriteBarrier();
    return v;
}
static inline void gb_store_u32(void *p, uint32_t v) {
    _ReadWriteBarrier();
    *(volatile uint32_t *)p = v;
    _ReadWriteBarrier();
}

#else
/* GCC / Clang: full C11 stdatomic with explicit memory orders */
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

#endif /* _MSC_VER */

static inline void gb_memcpy(void *dst, const void *src, size_t n) {
    memcpy(dst, src, n);
}
#endif /* GB_ATOMICS_H */
