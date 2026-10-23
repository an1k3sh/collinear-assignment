#include "tlp.hpp"

namespace tlp {
namespace {
struct Random {
    uint64_t state = 14695981039346656037ULL;
    explicit Random(const std::vector<uint8_t>& bytes) {
        for (auto byte : bytes) { state ^= byte; state *= 1099511628211ULL; }
        state ^= bytes.size();
    }
    int pick(int n) {
        uint64_t z = (state += 0x9e3779b97f4a7c15ULL);
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
        return static_cast<int>((z ^ (z >> 31)) % static_cast<uint64_t>(n));
    }
};
Json lit(Json value) { return Json::array({"lit", value}); }
Json col(const std::string& table, const std::string& name) {
    return Json::array({"col", table, name});
}
Json number(Random& r, bool join, int depth) {
    int op = r.pick(depth ? 6 : 3);
    if (op == 0) return lit(r.pick(17)-8);
    if (op == 1) return lit(nullptr);
    if (op == 2 || op == 3)
        return col(join && r.pick(2) ? "u" : "t", std::array<const char*,3>{"id","k","v"}[r.pick(3)]);
    auto left = number(r, join, depth-1);
    auto right = number(r, join, depth-1);
    return Json::array({op == 4 ? "add" : "sub", left, right});
}
Json predicate(Random& r, bool join, int depth) {
    int op = r.pick(depth ? 10 : 6);
    if (op < 3) return Json::array({"gt", col(join && r.pick(2) ? "u" : "t","v"), lit(0)});
    if (op == 3) return Json::array({"isnull", number(r, join, 1)});
    if (op < 6) {
        auto left = number(r, join, 1);
        auto right = number(r, join, 1);
        return Json::array({std::array<const char*,6>{"eq","ne","lt","le","gt","ge"}[r.pick(6)],
                            left, right});
    }
    if (op == 6) return Json::array({"not", predicate(r, join, depth-1)});
    auto left = predicate(r, join, depth-1);
    auto right = predicate(r, join, depth-1);
    return Json::array({op < 9 ? "and" : "or", left, right});
}
Json aggregate(Random& r, bool join) {
    std::string function = std::array<const char*,5>{"count","sum","avg","min","max"}[r.pick(5)];
    Json arg = function == "count" && r.pick(2) ? Json(nullptr) : number(r, join, 1);
    return Json::array({"agg", function, arg});
}
}
Json generate(const std::vector<uint8_t>& bytes) {
    Random r(bytes);
    const std::string mode = std::array<const char*,9>{
        "rows","distinct","count","sum","avg","min","max","group","having"}[r.pick(9)];
    const std::string source = std::array<const char*,3>{"single","inner","left"}[r.pick(3)];
    const bool join = source != "single";
    Json c = {{"version",1}, {"mode",mode}, {"source",source}, {"tables",Json::object()},
              {"where",nullptr}, {"predicate",nullptr}, {"select",Json::array()},
              {"group_by",Json::array()}, {"value",nullptr}};
    for (const auto& table : {"t","u"}) {
        Json rows = Json::array();
        int n = r.pick(12) == 0 ? 0 : 6 + r.pick(11);
        for (int i = 0; i < n; ++i) {
            Json key = r.pick(7) == 0 ? Json(nullptr) : Json(r.pick(5)-2);
            Json value = r.pick(4) == 0 ? Json(nullptr) : Json(r.pick(19)-9);
            Json tag = r.pick(5) == 0 ? Json(nullptr) : Json(std::array<std::string,5>{
                "a","b","q'",std::string("x\0y",3),""}[r.pick(5)]);
            rows.push_back(Json::array({r.pick(31)-15,key,value,tag}));
        }
        c["tables"][table] = rows;
    }
    if (r.pick(3) != 0) c["where"] = predicate(r, join, 1);
    c["predicate"] = predicate(r, join, 1);
    if (mode == "rows" || mode == "distinct") {
        int count = 1 + r.pick(3);
        for (int i = 0; i < count; ++i)
            c["select"].push_back(r.pick(3) == 0 ? col(join && r.pick(2) ? "u":"t","tag") :
                                                  number(r, join, 2));
    } else {
        int count = mode == "group" ? 1+r.pick(2) : r.pick(3);
        for (int i = 0; i < count; ++i) {
            auto g = col(join && r.pick(2) ? "u" : "t", r.pick(3) ? "k" : "tag");
            if (r.pick(5) == 0) g = Json::array({"add",col("t","k"),lit(r.pick(3))});
            c["group_by"].push_back(g);
        }
        if (mode == "group") c["select"] = c["group_by"];
        else if (mode == "having") {
            auto sum = Json::array({"agg","sum",col("t","v")});
            c["predicate"] = r.pick(2) ? Json::array({"gt",sum,lit(0)}) :
                                       Json::array({"le",aggregate(r,join),lit(r.pick(9)-4)});
            if (r.pick(3) == 0) c["predicate"] = Json::array({"not", c["predicate"]});
            c["select"].push_back(r.pick(2) ? aggregate(r,join) : sum);
            if (r.pick(3) == 0) c["select"].push_back(aggregate(r,join));
            if (count && r.pick(3) == 0) c["select"].push_back(c["group_by"][0]);
        } else {
            c["value"] = mode == "count" && r.pick(2) ? Json(nullptr) : number(r, join, 2);
        }
    }
    return c;
}
}
