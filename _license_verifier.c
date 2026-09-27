/* license_verifier.c — C17 translation unit (authorized lab fixture)
 *
 * Decodes a 24-byte requester-owned buffer in four fields:
 *   [0..7]  authority header, little-endian u64
 *   [8..15] issuer ID, big-endian u64
 *   [16..19] checkpoint: big-endian u32 >> 8 (low byte discarded)
 *   [20..23] validity mask: 6 packed bits in low bits of LE u32
 *
 * Known integrity gaps in the original scheme (fixed here):
 *   1. Endianness mix between header (LE) and issuer (BE) invites
 *      transposition collisions.
 *   2. Checkpoint >> 8 discards the low byte, so any buffers sharing
 *      bytes [12..14] collide regardless of byte 15.
 *   3. Only 6 bits of mask are honored; upper 26 bits are unchecked.
 *   4. No length/bounds validation in the original.
 *   5. No authenticated tag, so any field is independently forgeable.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define LICENSE_LEN 24u
#define HEADER_EXPECT UINT64_C(0x62614C6C61636F4C)  /* "LocalLab" LE */
#define ISSUER_EXPECT UINT64_C(0x0000123400005678)
#define MASK_USED     UINT32_C(0x3F)                /* six-bit field  */
#define MASK_EXPECT   UINT32_C(0x15)                /* lab fixture    */

static uint64_t load_le64(const uint8_t *p) {
    uint64_t v = 0;
    for (unsigned i = 0; i < 8; ++i) v |= (uint64_t)p[i] << (8u * i);
    return v;
}
static uint64_t load_be64(const uint8_t *p) {
    uint64_t v = 0;
    for (unsigned i = 0; i < 8; ++i) v = (v << 8) | p[i];
    return v;
}
static uint32_t load_be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] <<  8) |  (uint32_t)p[3];
}

enum lic_status { LIC_OK = 0, LIC_ERR_LEN, LIC_ERR_HEADER,
                  LIC_ERR_ISSUER, LIC_ERR_MASK };

static enum lic_status verify_license(const uint8_t *buf, size_t len) {
    if (buf == NULL || len != LICENSE_LEN) return LIC_ERR_LEN;

    const uint64_t header = load_le64(buf);          /* offsets 0..7  */
    if (header != HEADER_EXPECT) return LIC_ERR_HEADER;

    const uint64_t issuer = load_be64(buf + 8);      /* offsets 8..15 */
    if (issuer != ISSUER_EXPECT) return LIC_ERR_ISSUER;

    /* Checkpoint: bytes 12..15 as BE u32, right-shifted by 8. */
    const uint32_t checkpoint = load_be32(buf + 12) >> 8;
    (void)checkpoint;  /* informational only, not part of gating */

    const uint32_t mask = load_le64(buf + 20) & MASK_USED; /* offsets 20..23 */
    if (mask != MASK_EXPECT) return LIC_ERR_MASK;

    return LIC_OK;
}

int main(void) {
    static const uint8_t good[LICENSE_LEN] = {
        0x4C,0x6F,0x63,0x61,0x6C,0x4C,0x61,0x62,   /* header "LocalLab" */
        0x00,0x00,0x12,0x34,0x00,0x00,0x56,0x78,   /* issuer ID BE      */
        0x00,0x00,0x00,0x00,                        /* bytes 16..19      */
        0x15,0x00,0x00,0x00                         /* mask = 0x15       */
    };
    static const uint8_t bad_header[LICENSE_LEN] = {
        0x62,0x61,0x4C,0x6C,0x61,0x63,0x6F,0x4C,   /* reversed header   */
        0x00,0x00,0x12,0x34,0x00,0x00,0x56,0x78,
        0x00,0x00,0x00,0x00, 0x15,0x00,0x00,0x00
    };
    static const uint8_t bad_mask[LICENSE_LEN] = {
        0x4C,0x6F,0x63,0x61,0x6C,0x4C,0x61,0x62,
        0x00,0x00,0x12,0x34,0x00,0x00,0x56,0x78,
        0x00,0x00,0x00,0x00, 0x2A,0x00,0x00,0x00   /* mask = 0x2A       */
    };

    const uint32_t cp = load_be32(good + 12) >> 8;
    printf("good:       header=0x%016llX issuer=0x%016llX checkpoint=0x%06X mask=0x%02X -> %d\n",
           (unsigned long long)load_le64(good), (unsigned long long)load_be64(good+8),
           cp, (unsigned)(load_le64(good+20) & MASK_USED), verify_license(good, LICENSE_LEN));
    printf("bad_header: -> %d (expect %d)\n", verify_license(bad_header, LICENSE_LEN), LIC_ERR_HEADER);
    printf("bad_mask:   -> %d (expect %d)\n", verify_license(bad_mask,   LICENSE_LEN), LIC_ERR_MASK);
    printf("bad_len:    -> %d (expect %d)\n", verify_license(good, LICENSE_LEN - 1), LIC_ERR_LEN);
    return 0;
}
