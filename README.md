# fastbot_ros2_docker — CP23

目标环境：Ubuntu 22.04 / ROS 2 Humble / Gazebo Classic 11。

## 当前状态

Gazebo与SLAM容器已产生真实仿真输入和静止局部地图。Web镜像已完成HTTP文件服务、rosbridge、启动就绪检查及服务退出清理；本机浏览器已收到并绘制当前SLAM的/map，浏览器消息的时间戳及栅格SHA256与ROS端一致。

当前只验证静止局部地图，不是完整房间覆盖。摇杆到当前FastBot的接线、旧参考导航状态依赖、正式云端连接地址/CSP、Compose、Task2真机及官方评分尚未完成。Task1仍在进行，不把服务存活或网页可打开当作整项完成。

## 目录与来源

- simulation/Dockerfile.gazebo、Dockerfile.slam、Dockerfile.webapp：三项仿真镜像。
- simulation/entrypoint_gazebo.sh：为Gazebo/SLAM加载ROS与课程工作空间，再执行命令。
- simulation/entrypoint_webapp.sh：启动网页与rosbridge，等待服务并处理退出清理。
- simulation/check_web_services.py：启动阶段检查本机HTTP文件和WebSocket握手；失败则退出。
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

Gazebo/SLAM课程工作空间为/ros2_ws，分别默认运行课程场景与Cartographer。网页文件位于/webapp，HTTP监听容器8000端口，rosbridge监听9090端口；Web入口脚本同时管理两个服务，无需colcon构建网页文件。启动就绪检查最多观察15秒，与镜像构建时间无关；启动失败或任一服务意外退出时结束容器，停止时清理服务进程组。

## 已验证的本地连接方式

2026-11-04使用独立普通Docker bridge和统一ROS_DOMAIN_ID=181运行三容器；ROS_LOCALHOST_ONLY=0。仅Web容器向本机回环地址映射127.0.0.1:18000:8000和127.0.0.1:19090:9090，没有host网络或机器人设备访问。

浏览器访问http://127.0.0.1:18000/后，在页面连接框输入ws://127.0.0.1:19090，再点击连接。参考网页默认框仍是旧本机9226端口，需按实际端口映射修改。此次本机连接通过，不代表The Construct的正式域名、wss地址及CSP已适配。

本轮地图171×88、每格0.05米，时间戳及完整栅格hash在ROS和浏览器两端匹配；页面画布已实际绘制。没有发送摇杆、导航或速度消息。导航、相机和机器人位姿等旧参考功能尚未接入，不能把它们的空白或stale状态算作已验。Compose仍待实现，本轮运行仅作为隔离集成证据，不作为最终一键启动交付。

实际验证Web镜像：cp23-local/web-ready:c029-20261104，ID sha256:696fe56314b2f121bae2cfc6b663bc75abd6632c078823ffdcb459690d767ef4。本轮测试容器和网络均已清理，镜像缓存保留。

## 验证与记录边界

- Gazebo默认场景、基础消息、可见机器人、SLAM局部地图已有本机证据。
- Web依赖、5网页文件hash、HTTP响应、WebSocket握手、双服务正常停止已验。
- 分别占用HTTP/WebSocket端口时，启动就绪检查使容器非零退出；初次只检查进程退出而漏掉rosbridge重试的失败记录保留。
- 原生浏览器静止地图显示与ROS来源一致性已验；摇杆、完整房间、正式云端、Compose和真机尚待。
- Node语法、Bash语法、Python AST及选定Ruff检查、Git diff检查已执行。参考网页的整体格式基线差异保留，不批量重排；ShellCheck和部分VS Code界面诊断未验证。

学习尝试、原始构建/运行日志、浏览器会话和截图保留在本地忽略目录，不随源码提交。课程独立实现/迁移与官方验收门仍单独记录，当前不是Task1或Task2整体PASS。
