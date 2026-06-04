from setuptools import setup
import os
from glob import glob

package_name = 'lyra_localization'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (
            os.path.join('share', package_name, 'config'),
            glob('lyra_localization/config/*.yaml')
        ),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='veerobot',
    maintainer_email='veerobot@todo.todo',
    description='Lyra robot localization and odometry nodes',
    license='Apache License 2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'odom_node = lyra_localization.odom_node:main',
            'wheel_odom_node = lyra_localization.wheel_odom_node:main',
        ],
    },
)
