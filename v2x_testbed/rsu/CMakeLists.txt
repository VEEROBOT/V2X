cmake_minimum_required(VERSION 3.16)
project(v2x_rsu VERSION 1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Find OpenSSL
find_package(OpenSSL REQUIRED)

# Build the shared protocol library (in-tree)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../protocol
                 ${CMAKE_CURRENT_BINARY_DIR}/protocol_build)

# =============================================================================
# RSU Server
# =============================================================================

add_executable(rsu_server
    src/main.cpp
    src/registration_client.cpp
    src/udp_server.cpp
    src/packet_processor.cpp
    src/session_manager.cpp
    src/receive_buffer.cpp
    src/log_sender.cpp
)

target_include_directories(rsu_server PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/../protocol
)

target_link_libraries(rsu_server PRIVATE
    v2x_protocol
    pthread
)
