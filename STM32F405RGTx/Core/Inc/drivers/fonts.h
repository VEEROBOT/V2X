#ifndef FONTS_H
#define FONTS_H

#include <stdint.h>
#include <string.h>

typedef struct {
    uint8_t FontWidth;
    uint8_t FontHeight;
    const uint16_t *data;
} FontDef_t;

typedef struct {
    uint16_t Length;
    uint16_t Height;
} FONTS_SIZE_t;

extern FontDef_t Font_7x10;
extern FontDef_t Font_11x18;
extern FontDef_t Font_16x26;

#endif
