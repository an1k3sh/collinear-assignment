#include "tlp.hpp"
#include <sqlite3.h>
#include <memory>
#include <stdexcept>

namespace tlp {
namespace {
using Statement = std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)>;
void require(bool ok, const std::string& message) {
    if (!ok) throw std::runtime_error(message);
}
void bind_values(sqlite3_stmt* stmt, const std::vector<Json>& values) {
    require(sqlite3_bind_parameter_count(stmt) == static_cast<int>(values.size()),
            "binding count mismatch");
    for (size_t i = 0; i < values.size(); ++i) {
        int rc;
        const auto& v = values[i];
        int index = static_cast<int>(i + 1);
        if (v.is_null()) rc = sqlite3_bind_null(stmt, index);
        else if (v.is_number_integer()) rc = sqlite3_bind_int64(stmt, index, v.get<int64_t>());
        else if (v.is_number_float()) rc = sqlite3_bind_double(stmt, index, v.get<double>());
        else if (v.is_string()) {
            auto s = v.get<std::string>();
            rc = sqlite3_bind_text(stmt, index, s.data(), static_cast<int>(s.size()), SQLITE_TRANSIENT);
        } else throw std::runtime_error("unsupported binding");
        require(rc == SQLITE_OK, "binding failed");
    }
}
class Database {
    std::unique_ptr<sqlite3, decltype(&sqlite3_close)> db{nullptr, sqlite3_close};
    Statement prepare(const std::string& sql) {
        sqlite3_stmt* raw = nullptr;
        const char* tail = nullptr;
        int rc = sqlite3_prepare_v2(db.get(), sql.c_str(), -1, &raw, &tail);
        Statement stmt(raw, sqlite3_finalize);
        require(rc == SQLITE_OK && raw, sqlite3_errmsg(db.get()));
        require(!tail || std::string(tail).find_first_not_of(" \t\r\n;") == std::string::npos,
                "multiple statements");
        return stmt;
    }
public:
    explicit Database(const Json& c) {
        sqlite3* raw = nullptr;
        int rc = sqlite3_open(":memory:", &raw);
        db.reset(raw);
        require(rc == SQLITE_OK, "database open failed");
        for (const auto& name : {"t", "u"}) {
            auto create = prepare("CREATE TABLE " + std::string(name) +
                                  "(id INTEGER,k INTEGER,v INTEGER,tag TEXT)");
            require(sqlite3_step(create.get()) == SQLITE_DONE, "create failed");
            for (const auto& row : c.at("tables").at(name)) {
                auto insert = prepare("INSERT INTO " + std::string(name) + " VALUES(?,?,?,?)");
                bind_values(insert.get(), row.get<Row>());
                require(sqlite3_step(insert.get()) == SQLITE_DONE, "insert failed");
            }
        }
        sqlite3_set_authorizer(db.get(), [](void*, int action, const char*, const char*,
                                           const char*, const char*) {
            return action == SQLITE_SELECT || action == SQLITE_READ ||
                   action == SQLITE_FUNCTION || action == SQLITE_RECURSIVE ? SQLITE_OK : SQLITE_DENY;
        }, nullptr);
    }
    Rows execute(const Query& query) {
        auto stmt = prepare(query.sql);
        require(sqlite3_stmt_readonly(stmt.get()), "query must be read only");
        bind_values(stmt.get(), query.params);
        Rows result;
        int rc;
        while ((rc = sqlite3_step(stmt.get())) == SQLITE_ROW) {
            Row row;
            for (int i = 0; i < sqlite3_column_count(stmt.get()); ++i) {
                switch (sqlite3_column_type(stmt.get(), i)) {
                    case SQLITE_NULL: row.push_back(nullptr); break;
                    case SQLITE_INTEGER: row.push_back(sqlite3_column_int64(stmt.get(), i)); break;
                    case SQLITE_FLOAT: row.push_back(sqlite3_column_double(stmt.get(), i)); break;
                    case SQLITE_TEXT: row.push_back(std::string(
                        reinterpret_cast<const char*>(sqlite3_column_text(stmt.get(), i)),
                        sqlite3_column_bytes(stmt.get(), i))); break;
                    default: throw std::runtime_error("unsupported output type");
                }
            }
            result.push_back(row);
        }
        require(rc == SQLITE_DONE, sqlite3_errmsg(db.get()));
        return result;
    }
};
Json query_json(const Query& q) { return {{"sql", q.sql}, {"params", q.params}}; }
std::vector<uint8_t> decode(const std::string& hex) {
    require(hex.size() % 2 == 0, "odd hex length");
    std::vector<uint8_t> bytes;
    auto digit = [](char ch) -> int {
        if (ch >= '0' && ch <= '9') return ch - '0';
        if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
        if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
        throw std::runtime_error("invalid hex digit");
    };
    for (size_t i = 0; i < hex.size(); i += 2)
        bytes.push_back(static_cast<uint8_t>(16 * digit(hex[i]) + digit(hex[i+1])));
    return bytes;
}
}
Json inspect(const Json& request) {
    const auto op = request.at("op").get<std::string>();
    if (op == "equal")
        return {{"equal", equal(request.at("a").get<Rows>(), request.at("b").get<Rows>())}};
    if (op == "compose")
        return {{"rows", compose(request.at("case"), request.at("parts").get<std::array<Rows, 3>>())}};
    require(op == "inspect" || op == "case" || op == "inject" || op == "error",
            "unknown operation");
    auto c = op == "inspect" ? generate(decode(request.at("hex").get<std::string>())) :
                              request.at("case");
    auto plan = compile(c);
    Database db(c);
    int calls = 0;
    auto result = check(c, [&](const Query& query) {
        ++calls;
        if (op == "error") throw std::runtime_error("injected execution error");
        if (op == "inject" && calls == request.at("call").get<int>())
            return request.at("rows").get<Rows>();
        return db.execute(query);
    });
    return {{"case", c}, {"plan", {{"base", query_json(plan.base)},
                {"parts", {query_json(plan.parts[0]), query_json(plan.parts[1]),
                           query_json(plan.parts[2])}}}},
            {"result", {{"base", result.base}, {"combined", result.combined},
                        {"equivalent", result.equivalent}, {"calls", calls}}}};
}
void fuzz_one(const std::vector<uint8_t>& bytes) {
    auto c = generate(bytes);
    Database db(c);
    int calls = 0;
    auto result = check(c, [&](const Query& q) { ++calls; return db.execute(q); });
    require(calls == 4, "executor must be called exactly four times");
    require(result.equivalent, "TLP mismatch; replay this binary input");
}
}
