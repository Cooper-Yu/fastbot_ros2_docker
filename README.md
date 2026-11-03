# fastbot_ros2_docker — CP23

目标环境：Ubuntu 22.04 / ROS 2 Humble / Gazebo Classic 11。

当前已逐片实现Gazebo镜像的依赖安装、课程源码复制与包构建、环境准备脚本及默认启动配置。此前课程包构建、模型展开和默认入口局部验证通过；本次完整Dockerfile构建进行中。实际Gazebo服务、传感器/TF及GUI仍待验证。SLAM、WebApp、Compose和Task2真机部分尚未实现。

## 目录

- `simulation/Dockerfile.gazebo`：Gazebo镜像构建与启动配置。
- `simulation/entrypoint_gazebo.sh`：加载基础ROS和课程工作空间，再执行传入命令。
- `simulation/src/fastbot_description`：课程机器人描述与网格资源。
- `simulation/src/fastbot_gazebo`：课程世界、模型和启动文件。
- `environment.lock.json`：目标环境和已核对的基础镜像digest。
- `course_assets.lock.json`、`course_asset_manifest.json`：课程资源来源与逐文件hash。
- `.vscode/`、`.editorconfig`、`.yamllint`：工程编辑规则；不代表所有编辑器诊断都已验证。

## 构建

从仓库根目录执行：

```bash
docker build -f simulation/Dockerfile.gazebo -t fastbot-ros2-gazebo:local .
```

镜像内课程工作空间为`/ros2_ws`。默认入口为`/usr/local/bin/entrypoint_gazebo.sh`，默认命令为`ros2 launch fastbot_gazebo one_fastbot_room.launch.py`。运行所需的显示与通信配置仍在验证，待实际运行通过后补充启动命令。

## 来源与当前交付边界

课程运行资产来自用户确认的rosject1017054，来源工作副本为Galactic；本项目目标为Humble。保留上游文件及原有许可证标记，来源revision和实际文件内容由清单记录；本地读取权限调整不改变资源内容。发布许可仍待核对，当前未向Docker Hub或远端仓库发布。

这是进行中的课程项目；上述配置和局部验证不等于Task1、Task2或官方评分完成。运行日志、学习作答和诊断辅助脚本由忽略规则保留在本地，不作为项目交付文件。
