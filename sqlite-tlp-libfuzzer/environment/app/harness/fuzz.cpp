#include "tlp.hpp"
#include <cstdio>
#include <cstdlib>
#include <exception>
extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
    try {
        tlp::fuzz_one(std::vector<uint8_t>(data, data + size));
    } catch (const std::exception& e) {
        std::fprintf(stderr, "TLP failure: %s\n", e.what());
        std::abort();
    }
    return 0;
}
