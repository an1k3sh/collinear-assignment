#pragma once
#include <array>
#include <cstdint>
#include <functional>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>

namespace tlp {
using Json = nlohmann::json;
using Row = std::vector<Json>;
using Rows = std::vector<Row>;
struct Query { std::string sql; std::vector<Json> params; };
struct Plan { Query base; std::array<Query, 3> parts; };
struct Result { Rows base, combined; bool equivalent; };
using Executor = std::function<Rows(const Query&)>;

Json generate(const std::vector<uint8_t>& bytes);
Plan compile(const Json& c);
Rows compose(const Json& c, const std::array<Rows, 3>& parts);
bool equal(const Rows& a, const Rows& b);
Result check(const Json& c, const Executor& execute);

Json inspect(const Json& request);
void fuzz_one(const std::vector<uint8_t>& bytes);
}
