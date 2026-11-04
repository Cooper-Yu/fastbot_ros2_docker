"""Coach integration: Nav2 consumes the live Cartographer map; one adapter owns output."""

import json
from pathlib import Path
from launch import LaunchDescription
from launch.actions import GroupAction
from launch_ros.actions import Node, PushRosNamespace
from nav2_common.launch import RewrittenYaml
from launch_ros.parameter_descriptions import ParameterFile


def generate_launch_description():
    params = ParameterFile(
        RewrittenYaml(
            source_file='/dashboard/nav2.yaml',
            root_key='fastbot_nav',
            param_rewrites={},
            convert_types=True,
        ),
        allow_substs=True,
    )
    servers = [
        ('nav2_controller', 'controller_server'),
        ('nav2_planner', 'planner_server'),
        ('nav2_smoother', 'smoother_server'),
        ('nav2_behaviors', 'behavior_server'),
        ('nav2_bt_navigator', 'bt_navigator'),
        ('nav2_waypoint_follower', 'waypoint_follower'),
        ('nav2_velocity_smoother', 'velocity_smoother'),
    ]
    nodes = []
    for package, executable in servers:
        remaps = []
        if executable in ('controller_server', 'behavior_server', 'velocity_smoother'):
            remaps.append(('cmd_vel', '/fastbot_web/nav_raw'))
        if executable == 'velocity_smoother':
            remaps.append(('cmd_vel_smoothed', '/fastbot_web/nav_cmd'))
        nodes.append(
            Node(
                package=package,
                executable=executable,
                name=executable,
                output='screen',
                parameters=[params],
                remappings=remaps,
            )
        )
    nodes.append(
        Node(
            package='nav2_lifecycle_manager',
            executable='lifecycle_manager',
            name='lifecycle_manager_navigation',
            output='screen',
            parameters=[
                {
                    'use_sim_time': True,
                    'autostart': True,
                    'node_names': [name for _, name in servers],
                    'bond_timeout': 4.0,
                }
            ],
        )
    )
    # Use the real saved room map after stopping Cartographer; never run two map/TF owners.
    map_path = Path('/data/maps/room.yaml')
    pose_path = Path('/data/maps/navigation_initial_pose.json')
    if not map_path.is_file() or not pose_path.is_file():
        raise RuntimeError('Save the actual map and measured initial pose before navigation')
    initial = json.loads(pose_path.read_text())
    localization = [
        Node(
            package='nav2_map_server',
            executable='map_server',
            name='map_server',
            output='screen',
            parameters=[{'use_sim_time': True, 'yaml_filename': str(map_path)}],
        ),
        Node(
            package='nav2_amcl',
            executable='amcl',
            name='amcl',
            output='screen',
            parameters=[
                '/dashboard/nav2.yaml',
                {
                    'use_sim_time': True,
                    'set_initial_pose': True,
                    'initial_pose': {
                        'x': initial['x'],
                        'y': initial['y'],
                        'z': 0.0,
                        'yaw': initial['yaw'],
                    },
                },
            ],
        ),
        Node(
            package='nav2_lifecycle_manager',
            executable='lifecycle_manager',
            name='lifecycle_manager_localization',
            output='screen',
            parameters=[
                {'use_sim_time': True, 'autostart': True, 'node_names': ['map_server', 'amcl']}
            ],
        ),
    ]
    return LaunchDescription(
        [*localization, GroupAction([PushRosNamespace('fastbot_nav'), *nodes])]
    )
