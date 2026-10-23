#pragma once
#include "tlp.hpp"
#include <string>

namespace tlp::detail {
// Canonical, type-preserving encoding of a cell/row (signed and unsigned JSON
// integers with equal value encode identically; real, integer, text, NULL differ).
std::string cell_key(const Json& v);
std::string row_key(const Row& r);
// SQLite ordering (NULL < numeric < text < other) used for MIN/MAX states.
int sql_compare(const Json& a, const Json& b);
}
