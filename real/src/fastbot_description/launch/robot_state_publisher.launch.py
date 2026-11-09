"""Publish a simplified, explicitly approximate FastBot visualization model."""

from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def setup(context):
    name = LaunchConfiguration('robot_name').perform(context)
    path = Path(get_package_share_directory('fastbot_description')) / 'config/fastbot.urdf'
    description = path.read_text().replace('fastbot', name)
    return [
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            namespace=name,
            parameters=[{'robot_description': description, 'use_sim_time': False}],
            output='screen',
        )
    ]


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument('robot_name', default_value='fastbot'),
            OpaqueFunction(function=setup),
        ]
    )
