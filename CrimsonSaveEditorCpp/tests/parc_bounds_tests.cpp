#include "save_parser_cpp.h"
#include "parc_serializer.h"
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

static void Set32(std::vector<uint8_t>& raw, size_t offset, uint32_t value) {
    std::memcpy(raw.data() + offset, &value, 4);
}

int main(int argc, char** argv) {
    if (argc != 3) return 2;
    const std::string scenario = argv[1];
    const std::filesystem::path path = argv[2];
    try {
        // One empty type, one seven-byte object header, no private game data.
        std::vector<uint8_t> raw(66, 0);
        raw[0] = raw[1] = 0xff;
        raw[2] = 4;
        raw[18] = raw[20] = 1;
        raw[24] = 'T';
        Set32(raw, 31, 1);
        Set32(raw, 35, static_cast<uint32_t>(raw.size()));
        Set32(raw, 43, 0xffffffff);
        Set32(raw, 47, 0xffffffff);
        Set32(raw, 51, 59);
        Set32(raw, 55, 7);
        raw[59] = 1;
        if (scenario == "missing_header") raw.resize(27);
        else if (scenario == "truncated_table") Set32(raw, 31, 2);
        else if (scenario == "invalid_class") Set32(raw, 39, 1);
        else if (scenario == "out_of_bounds") Set32(raw, 55, 8);
        else if (scenario == "wrapped_range") Set32(raw, 51, 0xfffffffe);
        else if (scenario == "overlapping_table") Set32(raw, 51, 39);
        else if (scenario == "truncated_object") Set32(raw, 55, 2);
        else if (scenario != "roundtrip") return 2;
        {
            std::ofstream file(path, std::ios::binary);
            file.write(reinterpret_cast<const char*>(raw.data()), raw.size());
            if (!file) throw std::runtime_error("Test fixture write failed");
        }
        bool rejected = false;
        try {
            const auto parsed = SaveParserCpp::ParseRawFile(path.string());
            if (scenario == "roundtrip" && ParcSerializer::Serialize(parsed, raw) != raw)
                throw std::logic_error("Valid object did not roundtrip byte-for-byte");
        } catch (const std::runtime_error&) { rejected = true; }
        if (rejected == (scenario == "roundtrip"))
            throw std::logic_error(rejected ? "Valid object rejected" : "Malformed PARC accepted");
        std::filesystem::remove(path);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        std::filesystem::remove(path);
        return 1;
    }
}
