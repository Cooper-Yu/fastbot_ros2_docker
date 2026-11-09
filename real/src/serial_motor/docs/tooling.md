# 工具入口

## 保存与提醒

- .vscode/settings.json 按语言选择 formatter，并开启保存排版。
- C++ 用 ROS2 ament_clang_format 基础风格：函数/类的大括号换行，短 if/for 的大括号同一行；2 空格，100 列。额外保留定义块间空行，clang-format 需 14+。
- .clang-tidy：命名与 60 行函数规模提醒；需要真实编译数据库，不自动拆分方法。
- Python：Ruff 的 PEP 8 风格排版/命名/语句及分支检查。本模板使用单引号，目标 Python 按 ROS 环境生成；语句数不等于行数。
- YAML：Prettier 保存排版，yamllint 命令检查；XML：XML 扩展排版与校验。
- EditorConfig 保持编码、换行与基础缩进。

如果 VS Code 打开的根目录不是本包，包内 .vscode 不会自动作为该窗口设置。
建包入口的 --editor-root 可向真实打开目录补缺失的 settings/extensions；已有文件保留并提示合并。
本包的 launch/tasks 适合直接打开本包或将本包作为多根工作区目录。
语言规则若在上层已有文件，生成器优先继承并报告，不悄悄覆盖既有规范。

## 使用

```bash
# 在实际包根目录；已有工具时执行。
python3 tools/check_style.py
doxygen docs/Doxyfile
```

检查入口只检查，不自动写回格式；缺少适用工具或 C++ 编译数据库返回未就绪状态，不输出伪造 PASS。
C++ 有源码时提供真实数据库路径：

```bash
python3 tools/check_style.py --compile-db /absolute/workspace/build/serial_motor
```

VS Code Tasks 提供规范、文档、构建、测试入口；构建/测试需要输入真实 workspace 路径。
先在所属 WSL 环境加载 ROS 与必要 overlay，再从该环境启动 VS Code，保证任务/调试继承环境。
C++ Debug 需要给出真实 ELF 绝对路径；Python Debug 使用当前实际 Python 文件。
这只是调试入口，是否命中断点必须实际验证。

## 行为观察

ROS 入口实现后才使用对应话题、rqt_graph、日志、rosbag2、PlotJuggler 和 launch_testing。
真实命令、QoS、输入、输出、就绪条件、等待上限与清理按当前任务补齐。
README 与工具模板不会自动接线 CMake 测试、填入运行参数或安装依赖。

## 验证记录

权威记录：TODO：链接已有课程 code_lab/plan.md、attempt.md、verification.md
规则版本、命令、受检文件、诊断、豁免/延期与实际结果记入课程 verification.md。
格式化成功不证明算法、ROS 接口或行为正确。

规范命令入口对 clang-tidy 所选的函数规模/命名诊断采用失败退出；编辑器保持普通提醒。合理豁免需明确检查名和理由，不能用压缩排版绕过检查。

Canvas 的包内示例以包根作为文件路径基准；统一 Obsidian vault 使用生成器 --vault-root 创建紧凑入口与原生文件卡，卡片链接包内真实文件，不复制学习证据。
