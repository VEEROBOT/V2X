from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'lyra_bridge'

setup(
    name=package_name,
    version='1.0.0',
    packages=['lyra_bridge'],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=[
        'setuptools',
        'pyserial>=3.5',
    ],
    zip_safe=True,
    maintainer='Lyra Robotics Team',
    maintainer_email='your.email@example.com',
    description='ROS2 bridge for Lyra STM32F405 motor controller',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'lyra_node = lyra_bridge.node:main',
        ],
    },
    python_requires='>=3.8',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Topic :: Scientific/Engineering :: Robotics',
    ],
)
