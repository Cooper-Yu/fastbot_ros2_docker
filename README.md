# fastbot_ros2_docker — CP23

目标环境：Ubuntu 22.04 / ROS 2 Humble / Gazebo Classic 11。

## 当前状态

完整英文网页已接入当前仿真URDF/STL、真实关节与地图位姿、相机、实测遥测、摇杆、持久航点及Nav2导航。实际13段探索生成整屋地图；非实体激光切片覆盖99.52%，家具/遮挡未知保留。地图保存回读15980格0差异。

同一最终镜像已实际完成Living room、Doorway、Bedroom三个目标，松开及未发零速的输入断线均归零。该完整网页/导航是用户授权的Coach工程支撑，非学习者独立PASS。复现入口：[完整网页运行说明](simulation/dashboard/README.md)，环境/镜像和源码见dashboard_runtime.lock.json。测试实例已清理，地图/航点与日志保留。

2026-11-09：Task1云端和Task2真机已按指南逐项功能复核，详见[评分指南审计](GRADING_GUIDE_AUDIT.md)。Task2包含公开仓库实际克隆及重新上电恢复；源码已推送GitHub，五个应用镜像已发布Docker Hub。正式评分NOT_SUBMITTED，学习者独立检查SKIPPED_BY_USER，不记独立PASS。

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

课程资产来自用户确认的rosject1017054，来源环境为Galactic，本项目在Humble运行。保留上游许可证标记；课程及参考资产的外部发布许可仍需核对。本地Git记录不等于已获Docker Hub或远端发布授权；用户已明确授权并完成源码及镜像公开发布，来源与上游许可证标记保持。

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
- 所有实际失败、运行日志、原生截图和清理证据保留在本地忽略目录；当前云端/Compose复核见GRADING_GUIDE_AUDIT.md；正式评分待提交，学习者整体独立按用户要求跳过。

课程记录在项目上一级目录；C032等网页支撑不是学习者整体PASS。当前工程功能及Git发布状态以上方当前状态和评分审计为准。

## Compose 学习与本机接线记录

simulation/compose.yaml中的构建、域编号、端口、开关与卷映射已由学习者逐片填写。本机资源接线与静止三服务集成、卷重建持久性已验，使用下方运行入口。后续运动/浏览器/云端回归已完成；减少帮助检查SKIPPED_BY_USER。学习者作答见attempt.md，当前指针见../progress.md。

## 当前本机 Compose 运行入口

三服务Compose的本机接线与静止集成已验证；参见[运行说明](simulation/COMPOSE_LOCAL.md)。核心compose.yaml由学习者逐片填写，本机资源/WSLg/退出接线由Coach支撑。实际镜像与源hash见compose_runtime.lock.json。命名卷重建持久性通过，当前测试实例/网络已清理、数据卷保留；新增运动/浏览器回归与减少帮助检查另待。此前Docker CLI不可用已恢复，未提交或推送本轮更改。

## Docker Hub 发布（2026-11-05）

实际仓库：[cooper992/cooper12138-cp22](https://hub.docker.com/r/cooper992/cooper12138-cp22)，三个tag为fastbot-ros2-gazebo、fastbot-ros2-slam、fastbot-ros2-webapp，平台linux/amd64。三项已推送并从远端拉取核对digest；固定信息见hub_release.lock.json。

simulation/compose.hub.yaml只覆盖镜像名称；可与核心compose.yaml及目标环境配置合并。本机配置仍见simulation/COMPOSE_LOCAL.md，不把WSLg宿主路径直接用于The Construct。云端Graphical Tools、webpage_address/rosbridge_address及摇杆/地图已复核；官方评分未提交，不记学习者整体PASS。


## The Construct 云端运行（2026-11-09复核）

Task1 云端使用 rosject1017054，系统 Ubuntu20.04，Docker26.1.3、docker-compose1.25.0。三个容器内部为 ROS2 Humble/Ubuntu22.04，镜像 digest 见 hub_release.lock.json。simulation/compose.cloud.yaml 是该环境专用接线，部署成 simulation/docker-compose.yml 后运行课程命令。

首次部署时，在云端 simulation 目录准备以下本机相关文件。cloud_passwd 是容器 UID 的最小账号映射，内容可公开，不含认证信息。

~~~bash
test ! -e .env && test ! -e cloud_passwd || exit 1
printf 'CP23_RUN_ID=cp23-cloud-manual\nCLOUD_UID=1026\nCLOUD_GID=1026\nDISPLAY=:1\n' > .env
printf 'root:x:0:0:root:/root:/bin/bash\nuser:x:1026:1026:CP23:/tmp:/bin/bash\n' > cloud_passwd
cp compose.cloud.yaml docker-compose.yml
docker-compose config --quiet
docker-compose pull
docker-compose up
~~~

若按digest拉取后`docker images`显示`<none>`，在仓库根目录运行`python3 simulation/tag_published_images.py`；它核对固定digest并为同一内容补回课程标签，不重新构建。完整GUI和相机需要足够的rosject外层额度；本轮曾因2.5GiB外层限制发生OOM，恢复资源后的完整配置才通过，详见审计。

项目应位于 ~/ros2_ws/src/fastbot_ros2_docker。已有运行时先核对当前 .env、容器归属和数据，保留运行记录。普通用户需要 Docker 组权限及有效的 Docker daemon。云端实际部署已保留 .env/cloud_passwd/docker-compose.yml，可直接在该目录运行 docker-compose up。

Graphical Tools 显示 Gazebo。Gazebo 内存上限为 4 GB，初始 2 GB 时 gzclient 触发 cgroup OOM 被终止，调整后重新启动三服务，gzclient 与完整场景恢复。Web 映射宿主7000到容器8000，ROSbridge映射9090。先在交互终端运行 webpage_address 和 rosbridge_address，用返回的 HTTPS 地址打开网页，将 WSS 地址填入 ROSbridge session URL 并 Connect。

云端网页已验证实际地图、课程机器人模型、800×800相机和新鲜遥测。网页摇杆的短距离运动、松开停车已由独立ROS观察确认。当前新建SLAM地图含未知区域，本地保存的整屋地图继续保留。正式课程评分尚未提交；Task2已完成真机和本机WSL外部验收。

课程源资产及网页文件已从已验证镜像补齐云端，145个文件SHA256与本地Git源一致。工程开发历史保留在本地Git，云端运行日志在runtime_logs/cloud_deploy_a7177061-b953-440a-a225-66ce590476c8。学习者减少帮助迁移检查按要求跳过，工程功能验证单独记录。

## Task2 真机运行（2026-11-09）

入口见[real/README.md](real/README.md)。两个linux/arm64镜像在Pi原生构建，真机传感器/SLAM、本机WSL外部话题/RViz2，以及实际关机断电后重新上电自动恢复已验证。两个ARM镜像已发布并从远端拉取核对digest；正式评分尚未提交，学习者独立检查SKIPPED_BY_USER。

## 评分指南源码入口

公开源码：https://github.com/Cooper-Yu/fastbot_ros2_docker

```bash
cd ~/ros2_ws/src
git clone https://github.com/Cooper-Yu/fastbot_ros2_docker.git
cd fastbot_ros2_docker
```

Task1仿真配置/启动见上文The Construct云端运行和simulation/COMPOSE_LOCAL.md。Task2真机配置、docker-compose兼容入口、启动及ROS环境准备见[real/README.md](real/README.md)。两个任务分别在simulation和real目录运行docker-compose up，避免在仓库根目录启动错误的场景。
