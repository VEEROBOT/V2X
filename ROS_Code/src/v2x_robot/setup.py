from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'v2x_robot'

setup(
    name=package_name,
    version='1.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools', 'opencv-python'],
    zip_safe=True,
    maintainer='Praveen Kumar',
    maintainer_email='pravi.khm@gmail.com',
    description='V2X lane-following robot: line follower, emergency handler, V2X bridge',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'line_follower_node          = v2x_robot.line_follower_node:main',
            'emergency_handler_node      = v2x_robot.emergency_handler_node:main',
            'v2x_bridge_node             = v2x_robot.v2x_bridge_node:main',
            'position_node               = v2x_robot.position_node:main',
            'position_broadcaster_node   = v2x_robot.position_broadcaster_node:main',
        ],
    },
)
