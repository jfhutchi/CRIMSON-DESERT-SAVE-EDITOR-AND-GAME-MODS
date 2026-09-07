#include "save_parser_cpp.h"
#include "save_writer.h"
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
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
        if (std::string(argv[1]) == "unsupported") {
            const std::string expected = "9a4beb127f9e748b148d6690c25cc9379a315bd56c28af6319fd559f1152ac00";
            std::ostringstream hex;
            for (auto byte : SaveWriter::GenerateSaveKey(2))
                hex << std::hex << std::setw(2) << std::setfill('0') << unsigned(byte);
            Require(hex.str() == expected, "Version 2 key changed");
            SaveWriter::WriteSaveFile(path.string(), RawBlob(), {});
            {
                std::fstream file(path, std::ios::binary | std::ios::in | std::ios::out);
                file.seekp(4);
                file.put(99);
            }
            for (const auto& key : {std::string(), expected}) {
                bool rejected = false;
                try { SaveParserCpp::ParseFile(path.string(), key); }
                catch (const std::runtime_error& e) {
                    rejected = std::string(e.what()).find("Unsupported save version") != std::string::npos;
                }
                Require(rejected, "Parser accepted an unsupported version");
            }
            std::vector<uint8_t> header(128, 0);
            header[4] = 99;
            bool rejected = false;
            try { SaveWriter::WriteSaveFile(path.string(), RawBlob(), header); }
            catch (const std::runtime_error&) { rejected = true; }
            Require(rejected, "Writer accepted an unsupported version");
            std::ifstream saved(path, std::ios::binary);
            saved.seekg(4);
            Require(saved.get() == 99, "Rejected write modified the destination");
            saved.close();
            std::filesystem::remove(path);
            return 0;
        }
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
