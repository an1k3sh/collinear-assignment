#include "tlp.hpp"
#include "engine_detail.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>
#include <unordered_map>

namespace tlp {
namespace detail {

std::string cell_key(const Json& v) {
    if (v.is_null()) return "N";
    if (v.is_boolean()) return v.get<bool>() ? "B1" : "B0";
    if (v.is_number_unsigned()) return "I" + std::to_string(v.get<uint64_t>());
    if (v.is_number_integer()) return "I" + std::to_string(v.get<int64_t>());
    if (v.is_number_float()) {
        double d = v.get<double>();
        if (d == 0) d = 0;  // fold -0.0 into 0.0 (they compare equal in SQL)
        if (std::isnan(d)) return "RNaN";
        uint64_t bits;
        std::memcpy(&bits, &d, sizeof bits);
        return "R" + std::to_string(bits);
    }
    if (v.is_string()) {
        const auto& s = v.get_ref<const std::string&>();
        return "S" + std::to_string(s.size()) + ":" + s;
    }
    return "J" + v.dump();
}

std::string row_key(const Row& r) {
    std::string out = std::to_string(r.size()) + "|";
    for (const auto& cell : r) {
        auto k = cell_key(cell);
        out += std::to_string(k.size()) + ":" + k;
    }
    return out;
}

namespace {
int rank(const Json& v) {
    if (v.is_null()) return 0;
    if (v.is_number()) return 1;
    if (v.is_string()) return 2;
    return 3;
}
}  // namespace

int sql_compare(const Json& a, const Json& b) {
    int ra = rank(a), rb = rank(b);
    if (ra != rb) return ra < rb ? -1 : 1;
    if (ra == 0) return 0;
    if (ra == 1) {
        if (a.is_number_integer() && b.is_number_integer()) {
            bool ua = a.is_number_unsigned() && a.get<uint64_t>() > uint64_t(INT64_MAX);
            bool ub = b.is_number_unsigned() && b.get<uint64_t>() > uint64_t(INT64_MAX);
            if (ua || ub) {
                if (ua && ub) {
                    auto x = a.get<uint64_t>(), y = b.get<uint64_t>();
                    return x < y ? -1 : x > y ? 1 : 0;
                }
                return ua ? 1 : -1;
            }
            auto x = a.get<int64_t>(), y = b.get<int64_t>();
            return x < y ? -1 : x > y ? 1 : 0;
        }
        long double x = a.get<long double>(), y = b.get<long double>();
        return x < y ? -1 : x > y ? 1 : 0;
    }
    if (ra == 2) {
        int c = a.get_ref<const std::string&>().compare(b.get_ref<const std::string&>());
        return c < 0 ? -1 : c > 0 ? 1 : 0;
    }
    auto x = a.dump(), y = b.dump();
    return x < y ? -1 : x > y ? 1 : 0;
}

}  // namespace detail

namespace {

using detail::cell_key;
using detail::row_key;

void fail(const std::string& m) { throw std::invalid_argument("invalid case: " + m); }

// Literal values become numbered SQLite parameters; identical values share one
// number so that repeated group-key expressions are textually identical.
class Emitter {
    std::vector<Json> params_;
    std::unordered_map<std::string, size_t> index_;

public:
    std::string param(const Json& v) {
        if (!(v.is_null() || v.is_number_integer() || v.is_string()))
            fail("unsupported literal " + v.dump());
        auto key = cell_key(v);
        auto it = index_.find(key);
        if (it == index_.end()) {
            params_.push_back(v);
            it = index_.emplace(key, params_.size()).first;
        }
        return "?" + std::to_string(it->second);
    }
    std::vector<Json> take() { return std::move(params_); }
};

const std::map<std::string, std::string> kCompare = {
    {"eq", "="}, {"ne", "<>"}, {"lt", "<"}, {"le", "<="}, {"gt", ">"}, {"ge", ">="}};

std::string agg_sql(const std::string& fn) {
    if (fn == "count") return "COUNT";
    if (fn == "sum") return "SUM";
    if (fn == "avg") return "AVG";
    if (fn == "min") return "MIN";
    if (fn == "max") return "MAX";
    fail("unknown aggregate " + fn);
    return {};
}

std::string expr(const Json& e, Emitter& em) {
    if (!e.is_array() || e.empty() || !e[0].is_string()) fail("malformed expression " + e.dump());
    const auto& op = e[0].get_ref<const std::string&>();
    auto arity = [&](size_t n) {
        if (e.size() != n + 1) fail("bad arity for " + op);
    };
    if (op == "col") {
        arity(2);
        auto table = e[1].get<std::string>(), column = e[2].get<std::string>();
        if (table != "t" && table != "u") fail("unknown table " + table);
        if (column != "id" && column != "k" && column != "v" && column != "tag")
            fail("unknown column " + column);
        return table + "." + column;
    }
    if (op == "lit") {
        arity(1);
        return em.param(e[1]);
    }
    if (op == "add" || op == "sub") {
        arity(2);
        return "(" + expr(e[1], em) + (op == "add" ? " + " : " - ") + expr(e[2], em) + ")";
    }
    if (auto it = kCompare.find(op); it != kCompare.end()) {
        arity(2);
        return "(" + expr(e[1], em) + " " + it->second + " " + expr(e[2], em) + ")";
    }
    if (op == "and" || op == "or") {
        arity(2);
        return "(" + expr(e[1], em) + (op == "and" ? " AND " : " OR ") + expr(e[2], em) + ")";
    }
    if (op == "not") {
        arity(1);
        return "(NOT " + expr(e[1], em) + ")";
    }
    if (op == "isnull") {
        arity(1);
        return "(" + expr(e[1], em) + " IS NULL)";
    }
    if (op == "agg") {
        arity(2);
        auto fn = e[1].get<std::string>();
        if (e[2].is_null()) {
            if (fn != "count") fail("only COUNT may omit its argument");
            return "COUNT(*)";
        }
        return agg_sql(fn) + "(" + expr(e[2], em) + ")";
    }
    fail("unknown operator " + op);
    return {};
}

std::string from_clause(const std::string& source) {
    if (source == "single") return " FROM t";
    if (source == "inner") return " FROM t JOIN u ON t.k = u.k";
    if (source == "left") return " FROM t LEFT JOIN u ON t.k = u.k";
    fail("unknown source " + source);
    return {};
}

bool is_legacy_aggregate(const std::string& mode) {
    return mode == "count" || mode == "sum" || mode == "avg" || mode == "min" || mode == "max";
}

// part: -1 baseline, 0 true, 1 false, 2 NULL partition.
Query build(const Json& c, int part) {
    const auto mode = c.at("mode").get<std::string>();
    const auto& where = c.at("where");
    const auto& group_by = c.at("group_by");
    const auto& select = c.at("select");
    Emitter em;
    std::string sql = "SELECT ";
    std::vector<std::string> items;

    auto list = [](const std::vector<std::string>& xs) {
        std::string out;
        for (size_t i = 0; i < xs.size(); ++i) out += (i ? ", " : "") + xs[i];
        return out;
    };

    if (mode == "rows" || mode == "distinct" || mode == "having") {
        if (!select.is_array() || select.empty()) fail("select must be nonempty");
        for (const auto& s : select) items.push_back(expr(s, em));
        if (mode == "distinct") sql += "DISTINCT ";
    } else if (mode == "group") {
        if (!group_by.is_array() || group_by.empty()) fail("group mode needs group_by");
        for (const auto& g : group_by) items.push_back(expr(g, em));
    } else if (is_legacy_aggregate(mode)) {
        for (const auto& g : group_by) items.push_back(expr(g, em));
        const auto& value = c.at("value");
        std::string arg = value.is_null() ? "*" : expr(value, em);
        if (value.is_null() && mode != "count") fail("only COUNT may use a NULL value");
        if (part >= 0 && (mode == "sum" || mode == "avg")) {
            items.push_back("SUM(" + arg + ")");
            items.push_back("COUNT(" + arg + ")");
        } else {
            items.push_back(agg_sql(mode) + "(" + arg + ")");
        }
    } else {
        fail("unknown mode " + mode);
    }
    sql += list(items);
    sql += from_clause(c.at("source").get<std::string>());

    std::string filter;
    if (part >= 0) {
        auto p = expr(c.at("predicate"), em);
        filter = part == 0 ? "(" + p + ")" : part == 1 ? "(NOT " + p + ")" : "(" + p + " IS NULL)";
    }
    const bool having = mode == "having";
    std::string w = where.is_null() ? "" : "(" + expr(where, em) + ")";
    if (!having && !filter.empty()) w = w.empty() ? filter : w + " AND " + filter;
    if (!w.empty()) sql += " WHERE " + w;

    bool grouped = mode == "group" || having || is_legacy_aggregate(mode);
    if (grouped && group_by.is_array() && !group_by.empty()) {
        std::vector<std::string> keys;
        for (const auto& g : group_by) keys.push_back(expr(g, em));
        sql += " GROUP BY " + list(keys);
    }
    if (having && !filter.empty()) sql += " HAVING " + filter;
    return {sql, em.take()};
}

void check_case(const Json& c) {
    if (!c.is_object()) fail("case must be an object");
    for (const char* key : {"mode", "source", "predicate", "where", "select", "value", "group_by"})
        if (!c.contains(key)) fail(std::string("missing key ") + key);
    if (!c.at("group_by").is_array() || !c.at("select").is_array()) fail("lists expected");
}

int64_t to_i64(const Json& v) {
    if (v.is_number_unsigned()) {
        auto u = v.get<uint64_t>();
        if (u > uint64_t(INT64_MAX)) throw std::overflow_error("integer out of range");
        return static_cast<int64_t>(u);
    }
    return v.get<int64_t>();
}

// Exact accumulator for SUM states: integers stay integers, reals promote.
struct Total {
    bool real = false;
    int64_t i = 0;
    double r = 0;
    void add(const Json& v) {
        if (v.is_null()) return;
        if (!v.is_number()) fail("non-numeric aggregate state " + v.dump());
        if (!real && v.is_number_integer()) {
            int64_t x = to_i64(v);
            if (!__builtin_add_overflow(i, x, &i)) return;
            throw std::overflow_error("integer overflow in SUM recomposition");
        }
        if (!real) {
            real = true;
            r = static_cast<double>(i);
        }
        r += v.is_number_integer() ? static_cast<double>(to_i64(v)) : v.get<double>();
    }
    Json json() const { return real ? Json(r) : Json(i); }
    double as_double() const { return real ? r : static_cast<double>(i); }
};

struct State {
    Row keys;
    int64_t count = 0;
    Total sum;
    Json best;  // MIN/MAX state, NULL when no non-NULL input
};

Rows merge_aggregates(const Json& c, const std::string& mode, const std::array<Rows, 3>& parts) {
    const size_t nkeys = c.at("group_by").size();
    const bool weighted = mode == "sum" || mode == "avg";
    const size_t width = nkeys + (weighted ? 2 : 1);
    std::vector<std::string> order;
    std::map<std::string, State> states;
    for (const auto& rows : parts) {
        for (const auto& row : rows) {
            if (row.size() != width) fail("partition row has wrong width");
            Row keys(row.begin(), row.begin() + static_cast<long>(nkeys));
            auto key = row_key(keys);
            auto [it, fresh] = states.try_emplace(key);
            if (fresh) {
                it->second.keys = keys;
                order.push_back(key);
            }
            auto& st = it->second;
            const auto& a = row[nkeys];
            if (mode == "count") {
                if (!a.is_null()) st.count += to_i64(a);
            } else if (weighted) {
                st.sum.add(a);
                const auto& n = row[nkeys + 1];
                if (!n.is_null()) st.count += to_i64(n);
            } else if (!a.is_null()) {
                int cmp = st.best.is_null() ? 0 : detail::sql_compare(a, st.best);
                if (st.best.is_null() || (mode == "min" ? cmp < 0 : cmp > 0)) st.best = a;
            }
        }
    }
    // An ungrouped aggregate always yields exactly one row (the empty-input state).
    if (nkeys == 0 && states.empty()) {
        states.emplace("", State{});
        order.push_back("");
    }
    Rows out;
    for (const auto& key : order) {
        const auto& st = states.at(key);
        Row row = st.keys;
        if (mode == "count") row.push_back(st.count);
        else if (mode == "sum") row.push_back(st.count == 0 ? Json(nullptr) : st.sum.json());
        else if (mode == "avg")
            row.push_back(st.count == 0 ? Json(nullptr)
                                        : Json(st.sum.as_double() / static_cast<double>(st.count)));
        else row.push_back(st.best);
        out.push_back(std::move(row));
    }
    return out;
}

}  // namespace

Plan compile(const Json& c) {
    check_case(c);
    return {build(c, -1), {build(c, 0), build(c, 1), build(c, 2)}};
}

Rows compose(const Json& c, const std::array<Rows, 3>& parts) {
    check_case(c);
    const auto mode = c.at("mode").get<std::string>();
    if (mode == "rows" || mode == "having") {
        Rows out;
        for (const auto& p : parts) out.insert(out.end(), p.begin(), p.end());
        return out;
    }
    if (mode == "distinct" || mode == "group") {
        Rows out;
        std::set<std::string> seen;
        for (const auto& p : parts)
            for (const auto& r : p)
                if (seen.insert(row_key(r)).second) out.push_back(r);
        return out;
    }
    if (is_legacy_aggregate(mode)) return merge_aggregates(c, mode, parts);
    fail("unknown mode " + mode);
    return {};
}

bool equal(const Rows& a, const Rows& b) {
    if (a.size() != b.size()) return false;
    std::vector<std::string> x, y;
    x.reserve(a.size());
    y.reserve(b.size());
    for (const auto& r : a) x.push_back(row_key(r));
    for (const auto& r : b) y.push_back(row_key(r));
    std::sort(x.begin(), x.end());
    std::sort(y.begin(), y.end());
    return x == y;
}

Result check(const Json& c, const Executor& execute) {
    Plan plan = compile(c);
    Rows base = execute(plan.base);
    std::array<Rows, 3> parts;
    for (size_t i = 0; i < 3; ++i) parts[i] = execute(plan.parts[i]);
    Rows combined = compose(c, parts);
    bool same = equal(base, combined);
    return {std::move(base), std::move(combined), same};
}
}  // namespace tlp
