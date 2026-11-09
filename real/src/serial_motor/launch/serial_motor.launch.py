"""Launch a motor driver; hardware access requires explicit enablement."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    defaults = {
        'robot_name': 'fastbot',
        'serial_enabled': 'false',
        'serial_port': '',
        'baud_rate': '57600',
        'wheel_radius': '0.032',
        'wheel_separation': '0.12',
        'encoder_cpr': '2537',
        'loop_rate': '30',
        'max_counts_per_loop': '50.0',
        'command_timeout': '0.5',
        'publish_tf': 'true',
        'use_sim_time': 'false',
    }
    numeric = {
        'baud_rate': int,
        'wheel_radius': float,
        'wheel_separation': float,
        'encoder_cpr': int,
        'loop_rate': int,
        'max_counts_per_loop': float,
        'command_timeout': float,
        'serial_enabled': bool,
        'publish_tf': bool,
        'use_sim_time': bool,
    }
    params = {
        key: ParameterValue(LaunchConfiguration(key), value_type=kind)
        for key, kind in numeric.items()
    }
    params['serial_port'] = ParameterValue(LaunchConfiguration('serial_port'), value_type=str)
    for key, suffix in [
        ('odom_frame', '_odom'),
        ('base_frame', '_base_link'),
        ('joint_prefix', '_'),
    ]:
        params[key] = PythonExpression(["'", LaunchConfiguration('robot_name'), suffix, "'"])
    return LaunchDescription(
        [
            *[DeclareLaunchArgument(key, default_value=value) for key, value in defaults.items()],
            Node(
                package='serial_motor',
                executable='motor_driver',
                name='motor_driver',
                namespace=LaunchConfiguration('robot_name'),
                parameters=[params],
                output='screen',
            ),
        ]
    )
