cmake_minimum_required(VERSION 3.16)
project(v2x_protocol VERSION 1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Find OpenSSL
find_package(OpenSSL REQUIRED)

# =============================================================================
# Shared Protocol Library
# =============================================================================

add_library(v2x_protocol STATIC
    crypto/placeholder_provider.cpp
    packets/packet_serializer.cpp
    common/timer.cpp
    common/key_store.cpp
    common/config_reader.cpp
    utils/hex_utils.cpp
)

target_include_directories(v2x_protocol PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
)

target_link_libraries(v2x_protocol PUBLIC
    OpenSSL::SSL
    OpenSSL::Crypto
)

# =============================================================================
# Unit Tests
# =============================================================================

# Test: Crypto provider
add_executable(test_crypto tests/test_crypto.cpp)
target_link_libraries(test_crypto PRIVATE v2x_protocol)

# Test: Packet serializer
add_executable(test_packets tests/test_packets.cpp)
target_link_libraries(test_packets PRIVATE v2x_protocol)

# Test: Full protocol flow (OBU + RSU simulation on localhost)
add_executable(test_protocol_flow tests/test_protocol_flow.cpp)
target_link_libraries(test_protocol_flow PRIVATE v2x_protocol)

# =============================================================================
# Custom target: run all tests
# =============================================================================

add_custom_target(run_tests
    COMMAND test_crypto
    COMMAND test_packets
    COMMAND test_protocol_flow
    DEPENDS test_crypto test_packets test_protocol_flow
    COMMENT "Running all unit tests..."
)
