#pragma once
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace SaveKeys {

static const uint8_t SAVE_BASE_KEY[31] = {
    0xC4,0x1B,0x8E,0x73,0x0D,0xF2,0x59,0xA6,0x37,0xCC,0x04,0xE9,0xB1,0x2F,0x96,0x68,
    0xDA,0x10,0x7A,0x85,0x3E,0x61,0xF9,0x22,0x4D,0xB8,0x0A,0xD7,0x5C,0x13,0xEF
};

static const char* VERSION_PREFIX_1 = "^Qgbrm/.#@`zsr]\\@rvfal#\"";
static const char* VERSION_PREFIX_2 = "^Pearl--#Abyss__@!!";
static const char* HMAC_SUFFIX = "PRIVATE_HMAC_SECRET_CHECK";

inline std::vector<uint8_t> GenerateSaveKey(uint16_t version) {
    if (version != 1 && version != 2) {
        throw std::runtime_error("Unsupported save version " + std::to_string(version));
    }
    const char* prefix = (version == 1) ? VERSION_PREFIX_1 : VERSION_PREFIX_2;
    std::string material = std::string(prefix) + HMAC_SUFFIX;

    std::vector<uint8_t> key(32, 0);
    for (size_t i = 0; i < 31 && i < material.size(); ++i) {
        key[i] = SAVE_BASE_KEY[i] ^ (uint8_t)material[i];
    }
    key[31] = 0x00;
    return key;
}

} // namespace SaveKeys
