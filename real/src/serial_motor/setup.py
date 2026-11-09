from glob import glob

from setuptools import find_packages, setup

package_name = 'serial_motor'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='yg-fastbot',
    maintainer_email='yg-fastbot@todo.todo',
    description='ROS 2 serial motor command and measured encoder feedback node.',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'motor_driver = serial_motor.motor_driver:main',
        ],
    },
)
