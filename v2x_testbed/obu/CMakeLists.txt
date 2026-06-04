cmake_minimum_required(VERSION 3.16)
project(v2x_obu VERSION 1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(OpenSSL REQUIRED)

# Build shared protocol library (in-tree)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../protocol
                 ${CMAKE_CURRENT_BINARY_DIR}/protocol_build)

# =============================================================================
# OBU Client
# =============================================================================

add_executable(obu_client
    src/main.cpp
    src/registration_client.cpp
    src/udp_client.cpp
    src/auth_client.cpp
)

target_include_directories(obu_client PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/../protocol
    ${CMAKE_CURRENT_SOURCE_DIR}/../rsu/src
)

target_link_libraries(obu_client PRIVATE
    v2x_protocol
    pthread
)
