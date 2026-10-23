#include "tlp.hpp"
#include <stdexcept>
namespace tlp {
Plan compile(const Json&) { throw std::logic_error("implement SQL compilation"); }
Rows compose(const Json&, const std::array<Rows, 3>&) {
    throw std::logic_error("implement partition recomposition");
}
bool equal(const Rows&, const Rows&) { throw std::logic_error("implement comparison"); }
Result check(const Json&, const Executor&) { throw std::logic_error("implement execution"); }
}
