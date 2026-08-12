cmake_minimum_required(VERSION 3.10)
project(g1_quest_phase4_safety LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(g1_quest_safety src/supervisor.cpp)
target_include_directories(g1_quest_safety PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_options(g1_quest_safety PRIVATE -Wall -Wextra -Wpedantic)

enable_testing()
add_executable(g1_quest_safety_tests tests/supervisor_tests.cpp)
target_link_libraries(g1_quest_safety_tests PRIVATE g1_quest_safety)
target_compile_options(g1_quest_safety_tests PRIVATE -Wall -Wextra -Wpedantic)
add_test(NAME g1_quest_safety_tests COMMAND g1_quest_safety_tests)
