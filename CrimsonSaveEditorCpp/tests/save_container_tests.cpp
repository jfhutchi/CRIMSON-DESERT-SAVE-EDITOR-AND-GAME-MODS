#include "save_parser_cpp.h"
#include "save_writer.h"
#include <cstring>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <vector>

static void Require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

// One empty synthetic type and an empty TOC, sufficient for container tests.
static std::vector<uint8_t> RawBlob() {
    std::vector<uint8_t> raw(39, 0);
    raw[0] = raw[1] = 0xff;
    raw[2] = 4;
    raw[18] = 1; // type_count
    raw[20] = 1; // root name length
    raw[24] = 'T';
    raw[35] = 39; // TOC stream size
    return raw;
}

int main(int argc, char** argv) {
    if (argc != 3) return 2;
    const auto path = std::filesystem::path(argv[2]);
    try {
        const auto version = static_cast<uint16_t>(std::stoi(argv[1]));
        auto raw = RawBlob();
        std::vector<uint8_t> header(128, 0);
        std::memcpy(header.data() + 4, &version, sizeof(version));
        SaveWriter::WriteSaveFile(path.string(), raw, header);
        const auto parsed = SaveParserCpp::ParseFile(path.string());
        Require(parsed.container.version == version, "Writer changed the container version");
        Require(parsed.container.hmac_ok, "Written container HMAC failed");
        Require(parsed.raw_blob == raw, "Written payload did not roundtrip");
        std::filesystem::remove(path);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        std::filesystem::remove(path);
        return 1;
    }
}
