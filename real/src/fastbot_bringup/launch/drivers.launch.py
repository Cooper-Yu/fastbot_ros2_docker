"""Coordinate motor, model and optional sensor drivers using official topic names."""

from pathlib import Path

from serial_motor.device_paths import LIDAR_USB_IDS, resolve_serial_device
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def setup(context):
    def value(key):
        return LaunchConfiguration(key).perform(context)

    name = value('robot_name')
    motor = Path(get_package_share_directory('serial_motor')) / 'launch/serial_motor.launch.py'
    model = (
        Path(get_package_share_directory('fastbot_description'))
        / 'launch/robot_state_publisher.launch.py'
    )
    nodes = [
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(motor)),
            launch_arguments={
                'robot_name': name,
                'serial_enabled': value('serial_enabled'),
                'serial_port': value('serial_port'),
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(model)), launch_arguments={'robot_name': name}.items()
        ),
    ]
    if value('lidar_enabled').lower() == 'true':
        params = Path(get_package_share_directory('fastbot_bringup')) / 'config/lidar.yaml'
        nodes.append(
            Node(
                package='lslidar_driver',
                executable='lslidar_driver_node',
                name='lslidar_driver_node',
                namespace=name,
                parameters=[
                    str(params),
                    {
                        'serial_port_': resolve_serial_device(
                            value('lidar_port'), 'lslidar', LIDAR_USB_IDS
                        ),
                        'frame_id': name + '_laser_link',
                        'scan_topic': 'scan',
                    },
                ],
                output='screen',
            )
        )
    if value('camera_enabled').lower() == 'true':
        nodes.append(
            Node(
                package='v4l2_camera',
                executable='v4l2_camera_node',
                name='camera',
                namespace=name + '_camera',
                parameters=[
                    {
                        'video_device': value('camera_device'),
                        'image_size': [320, 240],
                        'camera_frame_id': name + '_camera_optical_frame',
                    }
                ],
                output='screen',
            )
        )
    return nodes


def generate_launch_description():
    defaults = {
        'robot_name': 'fastbot',
        'serial_enabled': 'true',
        'serial_port': '',
        'lidar_enabled': 'true',
        'camera_enabled': 'true',
        'lidar_port': '',
        'camera_device': '/dev/video0',
    }
    return LaunchDescription(
        [
            *[DeclareLaunchArgument(k, default_value=v) for k, v in defaults.items()],
            OpaqueFunction(function=setup),
        ]
    )
