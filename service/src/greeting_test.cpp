#include <greeting.hpp>

#include <userver/utest/utest.hpp>

using build_study::UserType;

UTEST(SayHelloTo, Basic) {
    EXPECT_EQ(build_study::SayHelloTo("Developer", UserType::kFirstTime), "Hello, Developer!\n");
    EXPECT_EQ(build_study::SayHelloTo({}, UserType::kFirstTime), "Hello, unknown user!\n");

    EXPECT_EQ(build_study::SayHelloTo("Developer", UserType::kKnown), "Hi again, Developer!\n");
    EXPECT_EQ(build_study::SayHelloTo({}, UserType::kKnown), "Hi again, unknown user!\n");
}