#include "tlp.hpp"
#include <algorithm>
#include <string>
#include <vector>

// Byte-to-case decoder.
//
// The leading bytes (at most half the input) are decoded directly, one byte per
// grammar decision, into the mode, source, group keys and partitioning
// predicate, so small libFuzzer mutations there make local structural edits.
// The bytes that were not consumed seed a deterministic local PRNG that expands
// the remaining structure (existing WHERE, projections, aggregate value) and
// the table contents. If the direct region runs out, decisions continue from a
// PRNG seeded by the whole input. No process state is used.
namespace tlp {
namespace {

constexpr int kMaxDepth = 6;
constexpr int kBound = 1000;

uint64_t mix64(uint64_t z) {
    z += 0x9E3779B97F4A7C15ULL;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

uint64_t hash_bytes(const uint8_t* p, size_t n, uint64_t salt) {
    uint64_t h = 0xCBF29CE484222325ULL ^ mix64(salt ^ n);
    for (size_t i = 0; i < n; ++i) h = (h ^ p[i]) * 0x100000001B3ULL;
    return mix64(h ^ (n * 0x9E3779B97F4A7C15ULL));
}

class Choice {
public:
    virtual ~Choice() = default;
    virtual unsigned below(unsigned n) = 0;  // uniform-ish value in [0, n)
    bool chance(unsigned percent) { return below(100) < percent; }
    int range(int lo, int hi) { return lo + static_cast<int>(below(static_cast<unsigned>(hi - lo + 1))); }
    unsigned weighted(std::initializer_list<unsigned> weights) {
        unsigned total = 0;
        for (auto w : weights) total += w;
        unsigned x = below(total), i = 0;
        for (auto w : weights) {
            if (x < w) return i;
            x -= w;
            ++i;
        }
        return i - 1;
    }
};

class Prng final : public Choice {
    uint64_t state_;

public:
    explicit Prng(uint64_t seed) : state_(seed) {}
    uint64_t next() {
        state_ += 0x9E3779B97F4A7C15ULL;
        return mix64(state_);
    }
    unsigned below(unsigned n) override { return n <= 1 ? 0 : static_cast<unsigned>(next() % n); }
};

class Direct final : public Choice {
    const std::vector<uint8_t>& bytes_;
    size_t pos_ = 0, cap_;
    Prng fallback_;
    unsigned byte() { return pos_ < cap_ ? bytes_[pos_++] : static_cast<unsigned>(fallback_.next() & 0xFF); }

public:
    Direct(const std::vector<uint8_t>& bytes, size_t cap, uint64_t seed)
        : bytes_(bytes), cap_(std::min(cap, bytes.size())), fallback_(seed) {}
    unsigned below(unsigned n) override {
        if (n <= 1) return 0;
        if (n <= 256) return byte() % n;
        unsigned v = byte();
        v = (v << 8) | byte();
        return v % n;
    }
    size_t consumed() const { return pos_; }
};

const std::string kStrings[] = {"",   "a",  "b",   "A",  "ab", "q'", std::string("x\0y", 3), "\xC3\xA9", "\xCE\xBB",
                                "\xF0\x9F\x98\x80", " ", "a b", "1", "%_", "'' OR 1=1 --", "\"", "-1"};
const char* const kAlphabet[] = {"a", "b", "c", "'", "\"", " ", "1", "\xC3\xA9", "\xCE\xBB", "\xF0\x9F\x98\x80", "_", "%"};

Json string_value(Choice& c) {
    unsigned n = sizeof(kStrings) / sizeof(kStrings[0]);
    if (c.chance(88)) {
        return kStrings[c.below(n)];
    }
    std::string s;
    int len = c.range(0, 32);
    for (int i = 0; i < len; ++i) {
        if (c.chance(6)) s.push_back('\0');
        else s += kAlphabet[c.below(sizeof(kAlphabet) / sizeof(kAlphabet[0]))];
    }
    return s;
}

int int_value(Choice& c, int small) {
    switch (c.weighted({70, 15, 8, 7})) {
        case 0: return c.range(-small, small);
        case 1: return c.range(-20, 20);
        case 2: {
            static constexpr int edges[] = {kBound, -kBound, 0, 1, -1, 999, -999};
            return edges[c.below(7)];
        }
        default: return c.range(-kBound, kBound);
    }
}

Json lit(Json v) { return Json::array({"lit", std::move(v)}); }
Json node(const char* op, Json a, Json b) { return Json::array({op, std::move(a), std::move(b)}); }
Json node(const char* op, Json a) { return Json::array({op, std::move(a)}); }

const char* const kCompare[] = {"eq", "ne", "lt", "le", "gt", "ge"};
const char* const kAggregates[] = {"count", "sum", "avg", "min", "max"};

int depth_of(const Json& e) {
    if (!e.is_array() || e.empty()) return 0;
    const auto& op = e[0].get_ref<const std::string&>();
    if (op == "col" || op == "lit") return 1;
    int d = 0;
    for (size_t i = 1; i < e.size(); ++i) d = std::max(d, depth_of(e[i]));
    return 1 + d;
}

bool has_op(const Json& e, const std::string& want) {
    if (!e.is_array() || e.empty() || !e[0].is_string()) return false;
    if (e[0] == want) return true;
    if (e[0] == "lit") return false;
    for (size_t i = 1; i < e.size(); ++i)
        if (has_op(e[i], want)) return true;
    return false;
}

bool is_numeric(const Json& e) {
    const auto& op = e[0].get_ref<const std::string&>();
    if (op == "col") return e[2] != "tag";
    if (op == "lit") return e[1].is_number_integer();
    return op == "add" || op == "sub" || op == "agg";
}

struct Key {
    Json expr;
    int depth;
    bool numeric;
};

// Compositional expression grammar. Depth arguments are 1-based node depths;
// a node generated at depth d may only have children while d < maxd.
class Grammar {
public:
    Grammar(Choice& c, bool join, std::vector<Key> keys = {}) : c_(c), join_(join), keys_(std::move(keys)) {}

    Json column(bool numeric_only) {
        const char* table = join_ && c_.chance(45) ? "u" : "t";
        static const char* const cols[] = {"id", "k", "v", "tag"};
        unsigned i = numeric_only ? c_.weighted({25, 35, 40}) : c_.weighted({20, 28, 32, 20});
        return Json::array({"col", table, cols[i]});
    }

    Json int_lit() { return lit(int_value(c_, 4)); }

    // ---- row stage ----
    Json numeric(int d, int maxd) {
        if (d >= maxd || c_.chance(d == 1 ? 40 : 55)) return c_.chance(68) ? column(true) : int_lit();
        return node(c_.chance(55) ? "add" : "sub", numeric(d + 1, maxd), numeric(d + 1, maxd));
    }

    Json scalar(int d, int maxd) {
        switch (c_.weighted({58, 16, 14, 4})) {
            case 0: return numeric(d, maxd);
            case 1: return Json::array({"col", join_ && c_.chance(45) ? "u" : "t", "tag"});
            case 2: return lit(string_value(c_));
            default: return lit(nullptr);
        }
    }

    Json predicate(int d, int maxd) { return pred(d, maxd, false); }

    // ---- group stage ----
    Json aggregate(int d, int maxd) {
        const char* fn = kAggregates[c_.below(5)];
        bool star = std::string(fn) == "count" && c_.chance(40);
        if (d >= maxd) return Json::array({"agg", "count", nullptr});
        if (star) return Json::array({"agg", fn, nullptr});
        int argmax = std::min(maxd, d + 1 + static_cast<int>(c_.below(3)));
        return Json::array({"agg", fn, numeric(d + 1, argmax)});
    }

    const Key* fitting_key(int d, int maxd, bool numeric_only) {
        std::vector<const Key*> fit;
        for (const auto& k : keys_)
            if (d - 1 + k.depth <= maxd && (!numeric_only || k.numeric)) fit.push_back(&k);
        if (fit.empty()) return nullptr;
        return fit[c_.below(static_cast<unsigned>(fit.size()))];
    }

    Json gnumeric(int d, int maxd) {
        if (d < maxd && c_.chance(d == 1 ? 35 : 25))
            return node(c_.chance(55) ? "add" : "sub", gnumeric(d + 1, maxd), gnumeric(d + 1, maxd));
        unsigned pick = c_.weighted({50, 30, 20});
        if (pick == 1)
            if (auto k = fitting_key(d, maxd, true)) return k->expr;
        if (pick == 2) return int_lit();
        return aggregate(d, maxd);
    }

    Json gscalar(int d, int maxd) {
        switch (c_.weighted({60, 20, 12, 4})) {
            case 0: return gnumeric(d, maxd);
            case 1:
                if (auto k = fitting_key(d, maxd, false)) return k->expr;
                return gnumeric(d, maxd);
            case 2: return lit(string_value(c_));
            default: return lit(nullptr);
        }
    }

    Json group_predicate(int d, int maxd) { return pred(d, maxd, true); }

private:
    Choice& c_;
    bool join_;
    std::vector<Key> keys_;

    Json operand(int d, int maxd, bool group, bool numeric_only) {
        if (group) return numeric_only ? gnumeric(d, maxd) : gscalar(d, maxd);
        return numeric_only ? numeric(d, maxd) : scalar(d, maxd);
    }

    Json comparison(int d, int maxd, bool group) {
        const char* op = kCompare[c_.below(6)];
        switch (c_.weighted({70, 18, 12})) {
            case 0: return node(op, operand(d + 1, maxd, group, true), operand(d + 1, maxd, group, true));
            case 1: {
                Json text = group ? gscalar(d + 1, maxd) : Json::array({"col", join_ && c_.chance(45) ? "u" : "t", "tag"});
                return node(op, std::move(text), lit(string_value(c_)));
            }
            default: return node(op, operand(d + 1, maxd, group, false), operand(d + 1, maxd, group, false));
        }
    }

    // Requires d < maxd (a predicate always has children).
    Json pred(int d, int maxd, bool group) {
        bool nest = d + 1 < maxd;
        unsigned pick = c_.weighted({44, 10, nest ? 32u : 0u, nest ? 10u : 0u, nest ? 4u : 0u});
        switch (pick) {
            case 0: return comparison(d, maxd, group);
            case 1: return node("isnull", operand(d + 1, maxd, group, false));
            case 2: return node(c_.chance(50) ? "and" : "or", pred(d + 1, maxd, group), pred(d + 1, maxd, group));
            case 3: return node("not", pred(d + 1, maxd, group));
            default: return node("isnull", pred(d + 1, maxd, group));
        }
    }
};

Json group_key(Grammar& g, Choice& c) {
    Json e;
    switch (c.weighted({55, 20, 25})) {
        case 0: e = g.column(false); break;
        case 1: e = g.numeric(1, 3); break;
        default: e = node(c.chance(50) ? "add" : "sub", g.column(true), g.numeric(2, 3)); break;
    }
    if (!has_op(e, "col")) e = g.column(false);
    return e;
}

Json make_row(Choice& c, int index, int vd, int kd, const std::array<unsigned, 4>& nulls) {
    auto cell = [&](unsigned col, Json value) -> Json {
        return c.below(100) < nulls[col] ? Json(nullptr) : value;
    };
    Row row;
    row.push_back(cell(0, c.chance(50) ? index : int_value(c, vd)));
    row.push_back(cell(1, c.chance(92) ? c.range(-kd, kd) : int_value(c, vd)));
    row.push_back(cell(2, c.chance(94) ? c.range(-vd, vd) : int_value(c, vd)));
    row.push_back(cell(3, string_value(c)));
    return row;
}

Json make_table(Choice& c) {
    int n;
    switch (c.weighted({4, 30, 46, 20})) {
        case 0: n = 0; break;
        case 1: n = c.range(1, 6); break;
        case 2: n = c.range(7, 16); break;
        default: n = c.range(17, 32); break;
    }
    static constexpr int vds[] = {2, 3, 4, 6, 10};
    static constexpr int kds[] = {1, 2, 3, 5};
    static constexpr unsigned rates[] = {0, 10, 20, 30, 45};
    int vd = vds[c.below(5)], kd = kds[c.below(4)];
    std::array<unsigned, 4> nulls{};
    for (auto& r : nulls) r = c.chance(8) ? 100 : rates[c.below(5)];
    Json rows = Json::array();
    for (int i = 0; i < n; ++i) {
        if (!rows.empty() && c.chance(10)) rows.push_back(rows[c.below(static_cast<unsigned>(rows.size()))]);
        else rows.push_back(make_row(c, i, vd, kd, nulls));
    }
    return rows;
}

}  // namespace

Json generate(const std::vector<uint8_t>& bytes) {
    static const char* const modes[] = {"rows", "distinct", "group", "having", "count",
                                        "sum",  "avg",      "min",   "max"};
    static const char* const sources[] = {"single", "inner", "left"};
    const size_t n = bytes.size();
    const uint64_t whole = hash_bytes(bytes.data(), n, 0x5157);

    // Direct structural decoding from the leading half of the input.
    Direct d(bytes, (n + 1) / 2, whole ^ 0xD1CEULL);
    const std::string mode = modes[d.below(9)];
    const std::string source = sources[d.below(3)];
    const bool join = source != "single";
    const bool legacy = mode != "rows" && mode != "distinct" && mode != "group" && mode != "having";

    Grammar direct(d, join);
    Json group_by = Json::array();
    int nkeys = 0;
    if (mode == "group") nkeys = 1 + static_cast<int>(d.below(2));
    else if (mode == "having") nkeys = static_cast<int>(d.weighted({30, 50, 20}));
    else if (legacy) nkeys = static_cast<int>(d.weighted({45, 38, 17}));
    std::vector<Key> keys;
    for (int i = 0; i < nkeys; ++i) {
        Json e = group_key(direct, d);
        keys.push_back({e, depth_of(e), is_numeric(e)});
        group_by.push_back(std::move(e));
    }

    Json predicate;
    if (mode == "having") {
        Grammar g(d, join, keys);
        predicate = g.group_predicate(1, 2 + static_cast<int>(d.below(kMaxDepth - 1)));
    } else {
        predicate = direct.predicate(1, 2 + static_cast<int>(d.below(kMaxDepth - 1)));
    }

    // Local expansion of the remaining (unconsumed) bytes.
    const size_t used = d.consumed();
    const uint64_t tail_seed = used < n ? hash_bytes(bytes.data() + used, n - used, used) : whole ^ 0x7A11ULL;
    Prng r(tail_seed);
    Grammar row_stage(r, join);

    Json where = nullptr;
    if (r.chance(42)) where = row_stage.predicate(1, 2 + static_cast<int>(r.below(4)));

    Json select = Json::array();
    Json value = nullptr;
    if (mode == "rows" || mode == "distinct") {
        int count = 1 + static_cast<int>(r.below(3));
        for (int i = 0; i < count; ++i) select.push_back(row_stage.scalar(1, 1 + static_cast<int>(r.below(4))));
    } else if (mode == "group") {
        select = group_by;
    } else if (mode == "having") {
        Grammar g(r, join, keys);
        int count = 1 + static_cast<int>(r.below(3));
        for (int i = 0; i < count; ++i) select.push_back(g.gscalar(1, 1 + static_cast<int>(r.below(4))));
        bool any_agg = false;
        for (const auto& s : select) any_agg = any_agg || has_op(s, "agg");
        if (keys.empty() && !any_agg) {
            Json agg = g.aggregate(2, 4);
            select[0] = is_numeric(select[0]) && depth_of(select[0]) < kMaxDepth
                            ? node(r.chance(50) ? "add" : "sub", agg, select[0])
                            : agg;
        }
    } else if (!(mode == "count" && r.chance(35))) {
        value = row_stage.numeric(1, 1 + static_cast<int>(r.below(4)));
    }

    Json tables = {{"t", make_table(r)}, {"u", make_table(r)}};
    return {{"version", 1},      {"tables", tables}, {"source", source},
            {"predicate", predicate}, {"where", where},  {"mode", mode},
            {"select", select},  {"value", value},   {"group_by", group_by}};
}
}  // namespace tlp
