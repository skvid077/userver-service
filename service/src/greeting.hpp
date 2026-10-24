#pragma once

#include <string>
#include <string_view>

namespace build_study {

enum class UserType { kFirstTime, kKnown };

std::string SayHelloTo(std::string_view name, UserType type);

}  // namespace build_study