#include "tlp.hpp"
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
int main(int argc, char** argv) {
    try {
        if (argc == 3 && std::string(argv[1]) == "replay") {
            std::ifstream file(argv[2], std::ios::binary);
            if (!file) throw std::runtime_error("cannot open replay file");
            std::vector<uint8_t> bytes(std::istreambuf_iterator<char>(file), {});
            tlp::fuzz_one(bytes);
            std::cout << "{\"replayed\":true}\n";
            return 0;
        }
        if (argc != 1) throw std::runtime_error("usage: tlp_cli [replay FILE]");
        std::string line;
        while (std::getline(std::cin, line)) {
            auto answer = tlp::inspect(tlp::Json::parse(line));
            std::cout << answer.dump() << '\n';
        }
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "TLP error: " << e.what() << '\n';
        return 2;
    }
}
