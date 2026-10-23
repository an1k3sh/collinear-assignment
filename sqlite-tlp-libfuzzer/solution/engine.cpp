#include "tlp.hpp"
#include <algorithm>
#include <map>
#include <stdexcept>

namespace tlp {
namespace {
std::string expr(const Json& e, std::vector<Json>& params) {
    const std::string op = e.at(0);
    if (op == "col") return "\"" + e.at(1).get<std::string>() + "\".\"" +
                            e.at(2).get<std::string>() + "\"";
    if (op == "lit") { params.push_back(e.at(1)); return "?"; }
    if (op == "agg") {
        auto argument = e.at(2).is_null() ? "*" : expr(e.at(2), params);
        return e.at(1).get<std::string>() + "(" + argument + ")";
    }
    auto left = expr(e.at(1), params);
    if (op == "not") return "(NOT (" + left + "))";
    if (op == "isnull") return "((" + left + ") IS NULL)";
    static const std::map<std::string, std::string> symbols{
        {"add","+"},{"sub","-"},{"eq","="},{"ne","<>"},{"lt","<"},{"le","<="},
        {"gt",">"},{"ge",">="},{"and","AND"},{"or","OR"}};
    auto right = expr(e.at(2), params);
    return "(" + left + " " + symbols.at(op) + " " + right + ")";
}
std::string joined(const std::vector<std::string>& strings, const std::string& separator) {
    std::string out;
    for (const auto& s : strings) { if (!out.empty()) out += separator; out += s; }
    return out;
}
std::string key(Row row) {
    for (auto& value : row)
        if (value.is_number_float() && value.get<double>() == 0.0) value = 0.0;
    return Json(row).dump();
}
}
Plan compile(const Json& c) {
    const std::string mode = c.at("mode"), source = c.at("source");
    auto query = [&](int branch) {
        Query q;
        std::vector<std::string> terms;
        if (mode == "rows" || mode == "distinct" || mode == "group" || mode == "having") {
            for (const auto& e : c.at("select")) terms.push_back(expr(e, q.params));
        } else {
            for (const auto& e : c.at("group_by")) terms.push_back(expr(e, q.params));
            std::vector<std::string> functions{mode};
            if (branch >= 0 && (mode == "sum" || mode == "avg")) functions = {"sum","count"};
            for (const auto& f : functions) {
                auto arg = c.at("value").is_null() ? "*" : expr(c.at("value"), q.params);
                terms.push_back(f + "(" + arg + ")");
            }
        }
        q.sql = "SELECT " + std::string(mode == "distinct" ? "DISTINCT " : "") +
                joined(terms, ",") + " FROM t";
        if (source != "single")
            q.sql += std::string(source == "left" ? " LEFT JOIN" : " JOIN") + " u ON t.k=u.k";
        std::vector<std::string> conditions;
        if (!c.at("where").is_null()) conditions.push_back(expr(c.at("where"), q.params));
        auto partition = [&]() {
            auto p = expr(c.at("predicate"), q.params);
            if (branch == 0) return "(" + p + ")";
            if (branch == 1) return "(NOT (" + p + "))";
            return "((" + p + ") IS NULL)";
        };
        if (branch >= 0 && mode != "having") conditions.push_back(partition());
        if (!conditions.empty()) q.sql += " WHERE " + joined(conditions, " AND ");
        std::vector<std::string> groups;
        for (const auto& g : c.at("group_by")) groups.push_back("(" + expr(g, q.params) + ")");
        if (!groups.empty()) q.sql += " GROUP BY " + joined(groups, ",");
        if (branch >= 0 && mode == "having") q.sql += " HAVING " + partition();
        return q;
    };
    return {query(-1), {query(0), query(1), query(2)}};
}
bool equal(const Rows& a, const Rows& b) {
    std::map<std::string, int> counts;
    for (const auto& row : a) ++counts[key(row)];
    for (const auto& row : b) --counts[key(row)];
    return std::all_of(counts.begin(), counts.end(), [](const auto& item) { return item.second == 0; });
}
Rows compose(const Json& c, const std::array<Rows, 3>& parts) {
    const std::string mode = c.at("mode");
    Rows rows;
    for (const auto& part : parts) rows.insert(rows.end(), part.begin(), part.end());
    if (mode == "rows" || mode == "having") return rows;
    if (mode == "distinct" || mode == "group") {
        std::map<std::string, Row> unique;
        for (const auto& row : rows) unique[key(row)] = row;
        rows.clear();
        for (const auto& item : unique) rows.push_back(item.second);
        return rows;
    }
    const auto n = c.at("group_by").size();
    std::map<std::string, std::pair<Row, Rows>> grouped;
    for (const auto& row : rows) {
        if (row.size() < n + 1) throw std::runtime_error("short aggregate row");
        Row group(row.begin(), row.begin() + n);
        auto& entry = grouped[key(group)];
        entry.first = group;
        entry.second.emplace_back(row.begin() + n, row.end());
    }
    Rows out;
    for (const auto& item : grouped) {
        auto group = item.second.first;
        Json value = nullptr;
        int64_t total = 0, count = 0;
        for (const auto& state : item.second.second) {
            if (mode == "count") total += state.at(0).get<int64_t>();
            else if (mode == "sum" || mode == "avg") {
                if (!state.at(0).is_null()) total += state.at(0).get<int64_t>();
                count += state.at(1).get<int64_t>();
            } else if (!state.at(0).is_null()) {
                if (value.is_null() || (mode == "min" ? state[0] < value : state[0] > value))
                    value = state[0];
            }
        }
        if (mode == "count") value = total;
        if ((mode == "sum" || mode == "avg") && count != 0) {
            if (mode == "sum") value = total;
            else value = static_cast<double>(total) / static_cast<double>(count);
        }
        group.push_back(value);
        out.push_back(group);
    }
    return out;
}
Result check(const Json& c, const Executor& execute) {
    auto plan = compile(c);
    auto base = execute(plan.base);
    std::array<Rows, 3> parts;
    for (size_t i = 0; i < 3; ++i) parts[i] = execute(plan.parts[i]);
    auto combined = compose(c, parts);
    bool equivalent = equal(base, combined);
    return {base, combined, equivalent};
}
}
