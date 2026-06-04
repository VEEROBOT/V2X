cmake_minimum_required(VERSION 3.8)
project(lyra_config)

find_package(ament_cmake REQUIRED)

# Install config files
install(
  DIRECTORY config
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
