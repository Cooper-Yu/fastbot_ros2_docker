# fastbot_ros2_docker — CP23

目标环境：Ubuntu 22.04 / ROS 2 Humble / Gazebo Classic 11。

## 当前状态

完整英文网页已接入当前仿真URDF/STL、真实关节与地图位姿、相机、实测遥测、摇杆、持久航点及Nav2导航。实际13段探索生成整屋地图；非实体激光切片覆盖99.52%，家具/遮挡未知保留。地图保存回读15980格0差异。

同一最终镜像已实际完成Living room、Doorway、Bedroom三个目标，松开及未发零速的输入断线均归零。该完整网页/导航是用户授权的Coach工程支撑，非学习者独立PASS。复现入口：[完整网页运行说明](simulation/dashboard/README.md)，环境/镜像和源码见dashboard_runtime.lock.json。测试实例已清理，地图/航点与日志保留。

Task1仍STUDYING：课程三镜像/Compose核心、减少帮助整体独立检查、正式云端URL/CSP与官方评分另待；Task2真机未运行。本轮未commit/push。

## 目录与来源

- simulation/Dockerfile.gazebo、Dockerfile.slam、Dockerfile.webapp：三项仿真镜像。
- simulation/entrypoint_gazebo.sh：为Gazebo/SLAM加载ROS与课程工作空间，再执行命令。
- simulation/entrypoint_webapp.sh：启动网页与rosbridge，等待服务并处理退出清理。
- simulation/check_web_services.py：启动阶段检查本机HTTP文件和WebSocket握手；失败则退出。
- simulation/manual_bridge.py：仿真专用输入转接、限速和输入/反馈超时归零支撑。
- simulation/src/：课程机器人描述、场景与Cartographer入口最小包。
- simulation/webapp/fastbot_webapp/：复用的本地独立工程参考网页；不是官方提供的网页或学习者已独立完成的网页作业。
- environment.lock.json：目标环境与已核基础镜像digest。
- course_assets.lock.json、course_asset_manifest.json、slam_course_assets.lock.json：课程资产来源、范围与hash。
- webapp_assets.lock.json：参考网页来源、原始hash与本项目适配记录。
- .vscode/、.editorconfig、.prettierrc.json、.yamllint：编辑与检查支持，不代表全部编辑器功能均已验证。

课程资产来自用户确认的rosject1017054，来源环境为Galactic，本项目在Humble运行。保留上游许可证标记；课程及参考资产的外部发布许可仍需核对。本地Git记录不等于已获Docker Hub或远端发布授权；目前未推送仓库或镜像。

## 构建

从仓库根目录执行：

```bash
docker build -f simulation/Dockerfile.gazebo -t fastbot-ros2-gazebo:local .
docker build -f simulation/Dockerfile.slam -t fastbot-ros2-slam:local .
docker build -f simulation/Dockerfile.webapp -t fastbot-ros2-webapp:local .
```

基础镜像为ros:humble-ros-base-jammy，实际验证digest见environment.lock.json；APT安装内容以构建时的软件源为准，实际构建日志和版本保存在本地证据中。运行时不重新安装依赖或colcon构建。

Gazebo/SLAM课程工作空间为/ros2_ws，分别默认运行课程场景与Cartographer。网页文件位于/webapp，HTTP监听容器8000端口，rosbridge监听9090端口；Web入口脚本管理HTTP与rosbridge；显式设置CP23_ENABLE_SIM_MANUAL=1后，再管理仿真手动转接程序。无需colcon构建网页文件。启动就绪检查最多观察15秒，与镜像构建时间无关；启动失败或任一服务意外退出时结束容器，停止时清理服务进程组。

## 本地运行与控制

完整网页入口见simulation/dashboard/README.md。公开帮助脚本已实际从新Gazebo实例启动：独立普通bridge、ROS_DOMAIN_ID=187、非root只读容器，宿主仅回环HTTP18000/WS19090。浏览器打开http://127.0.0.1:18000/，默认连接ws://127.0.0.1:19090，显式Connect；不会自动运动。当前测试服务已停止。

默认CP23_FULL_DASHBOARD=1启动带原子航点存储的HTTP服务。显式CP23_ENABLE_SIM_MANUAL=1才启相机和dashboard_adapter；CP23_ENABLE_NAVIGATION=true额外启Nav2（需要Dockerfile.dashboard-support镜像）。未启导航时仍可接收运行中Cartographer的真实/map；保存地图导航模式则使用map_server/AMCL，不同时跑Cartographer。

完整模式发布/fastbot_web/manual_cmd，由转接支撑基于真实odom/scan/TF和单最终发布者门检查后输出/fastbot/cmd_vel；0.05m/s、0.30rad/s上限，输入/反馈超时归零，退出先尝试零速。保留CP23_FULL_DASHBOARD=0的旧服务/手动转接支撑与学习者命令，但当前完整网页验收针对完整模式；不把旧话题路径描述为当前默认。

地图/航点保存在runtime_logs/dashboard_state；首次缺失时才从simulation/dashboard/data种子复制，不覆盖已有数据。重载后若出现succeeded-unowned，先确认实际任务结束与停车，再显式Reconcile idle恢复任务所有权；不自动重发目标。该本机仿真运行约定不用于真机认证。

## 验证与记录边界

- 实际原生浏览器核验英文完整布局、真实模型/关节/地图/相机/遥测、摇杆与持久航点。
- 真实SLAM整屋地图保留原始栅格、裁剪、来源、覆盖与map_server逐格回读证据；家具内部未知不伪填。
- 同一最终镜像中三个房间航点实际到达；原生松开约8ms输出零、独立客户端不发零速即断线后约0.339s输出零，均观察到停稳。仅本轮样本，不承诺硬实时/真机停车或精度校准。
- 22个运行文件与所测镜像SHA256一致，镜像ID/源码hash见dashboard_runtime.lock.json。
- Node/Bash/Python语法、XML、选定Ruff、ROSbridge分片合同和Git差异检查通过。ShellCheck及部分VS Code界面诊断仍未验证；不批量重排旧源码。
- 所有实际失败、运行日志、原生截图和清理证据保留在本地忽略目录；正式云端URL/CSP、Compose、学习者整体独立及官方门尚待。

课程记录在项目上一级目录；当前C032为用户授权Coach支撑完成，不是Task1或Task2整体PASS。本轮尚未commit/push；提交须审阅确认。
