# 注释检查与 Problems

C++包任务：`serial_motor: documentation (Problems)`。从包根运行 `doxygen docs/Doxyfile.check`；默认手动触发，不是保存自动检查，也不阻断colcon构建。

- 检查类、结构体、成员（包括private函数与变量）的文档缺失，参数名错误，以及已有函数文档缺少参数/返回值说明。范围受Doxygen提取能力限制，并非保证检查每个源码实体。
- 普通 `//` 区块注释和行内说明仍有价值，但不等于 `///` 或 `/** ... */` 文档。工具不判断是否英文、解释是否正确或是否有足够设计理由，人工审阅仍必要。
- 函数文档说明职责；有参数用@param，有需解释的返回值用@return，输出引用可用@param[out]。不要给void函数机械添加@return，不要求每条语句都有注释。
- 本检查另用Doxyfile.check继承现有HTML配置；警告输出到终端，Problems匹配绝对路径和行号。XML辅助产物在docs/generated/comment-check，属于已有忽略目录。
- 若打开整个ROS工作区，需把任务合并到实际editor-root，并把cwd指向包根；不要覆盖已有任务。VSCode任务支持存在不代表GUI检查通过。
- Doxygen有warning时仍可能exit0：这里只表示工具成功执行，不代表文档完整。逐步处理有价值的接口说明，不以批量灌入空泛注释消警告。

Ubuntu-22.04 Doxygen1.9.1验证了缺失成员说明、漏参数/返回值、错误参数名及完整文档对照。其他环境与版本需复验。此任务不是clang-tidy原生显示问题的修复。

## 函数注释固定结构（2026-10-09 暂定）

用户约定：先由学习者用自己的话说明函数，再整理为易读英文；默认顺序为 @brief、@par、@param、@return、@note。短标题也放进Doxygen块，使源码与生成文档都有标题。保留 @note None at present. 表示已检查且暂无补充，未来直接替换；TODO表示尚未完成，两者不要混淆。参数名必须真实且不加星号；多个参数逐项写，无参数不编造参数。无返回值按实际接口处理，不编造返回值。

当前完成段函数范例：

```cpp
/**
 * @brief Handle waiting and switching after a segment completes.
 *
 * @par Wait and switch
 * If the current segment is not completed, return false to continue tracking it.
 * Otherwise, keep the robot stopped until the waiting time has elapsed.
 * Then prepare the next segment, or shut down the node if all segments are completed.
 *
 * @param[in] current_time Current ROS time used to measure the waiting time.
 * @return False to continue tracking; true to end the current timer callback.
 * @note None at present.
 */
```

其他函数复用结构，按自身行为改写内容；不要复制本例的路段描述或bool返回语义到无关函数。此约定只更新文档模板，不自动重写既有源码，也不新增强制校验。Doxygen不负责验证说明是否正确或TODO是否完成。

2026-10-09 参数方向补充：已完成的函数文档显式标注@param[in]、@param[out]或@param[in,out]，按实际读写用途选择；const引用不意味着输出，修改类成员不使输入参数成为输出。当时已完成的五个函数只有输入与pid_dt输出；后续compute_and_publish_command使用[in,out]，应按实际接口判断。

## 参数方向与原因说明（2026-10-09 用户约定）

后续函数注释的每个@param必须根据实际用途写明[in]、[out]或[in,out]，并在说明文字中解释数据从哪里来、函数读取什么或写回什么。代码注释用英文；讲解与工程指南用中文。不是只贴标签，也不是按是否有&机械判断。

| 方向 | 数据流 | 判定理由与应说明的内容 |
|---|---|---|
| [in] | 调用者 → 函数 | 函数读取调用者提供的值，不通过此参数写回结果；说明值的来源和用途。 |
| [out] | 函数 → 调用者 | 函数写入结果，不依赖调用者原先存放的值；说明写回的结果、单位及何时有效。 |
| [in,out] | 调用者 → 函数 → 调用者 | 函数既依赖传入内容，又更新调用者可见的数据；说明读取部分和写回部分。结构体可以读取某些字段并输出另一些字段。 |

现有接口示例（按具体函数选用，不是要求每个函数凑齐三种方向）：

```cpp
 * @param[in] current_time ROS time supplied by the caller; read to calculate the interval.
 * @param[out] pid_dt Calculated interval written back in seconds; valid only on a false return.
 * @param[in,out] data Read errors, yaw, and PID interval supplied by the caller;
 * write raw, limited, and body-frame velocities back for logging.
```

审阅时检查：
- 输入是否在调用前准备好，输出是否在使用前真正写入；初始化为0不代表结果已计算。
- 普通按值参数即使在函数内被修改，也不会因此成为调用者的输出。
- const引用通常用于读取；非const引用可能用于输入、输出或两者，要看实际数据用途。
- 类成员被修改属于函数副作用，不等于某个输入参数是[out]。
- @return描述函数返回值，@param[out]描述通过参数写回，两条通路分别说明。
- 标签不改变C++行为，Doxygen不会替人工证明数据流正确；缺失字段映射仍需代码审查/测试。

保留brief/par/param/return/note的既定结构；非适用参数和返回值不编造。已完成文档后续修改时按此规则补充，新TODO不代填学习者的核心功能解释。

2026-10-09 参数来源/去向细化：参数说明应标明当前真实调用函数名、调用处变量或字段、被调用函数的读取用途、写回同一对象或变量的位置及后续使用函数；只写适用方向。引用输出注明有效返回条件。调用关系变化时同步更新，不为所有潜在调用者编造来源。当前范例：on_timer()创建data并填输入，compute_and_publish_command()读取误差/朝向/间隔并写回同一data的六个速度字段，log_control_state()只读该对象。函数参数注释用英文，教学解释用中文。

2026-10-09 Doxygen内部工程导航：HTML生成与注释检查应对齐私有/静态成员范围，显式EXTRACT_PRIVATE=YES、EXTRACT_STATIC=YES，保留EXTRACT_ALL=NO。网页缺少函数时先核对访问权限提取配置，再检查实际生成HTML；检查器零警告不证明网页已展示。CP18已验证，Windows模板及WSL22部署同步，其他环境未部署。

2026-10-09 流程图展示约定：Doxygen网页与VS Code Mermaid预览分别验证。未配置Mermaid渲染时不得声称围栏代码会成为网页图形；可使用Graphviz生成本地SVG，再配置IMAGE_PATH和image指令。替换模板占位节点为实际流程后，检查生成HTML的图像引用和文件存在，再确认浏览器显示。CP18采用此方案；模板不自动填入课程核心流程。

2026-10-09 Doxygen链接检查：仓库README中的源码相对链接不保证在生成HTML中有效。对已提取的源码使用Doxygen可识别的文件名/全限定方法引用，检查实际生成href及目标文件；没有文档输出的文件保留明确路径或另行配置复制，不能仅验证源文件存在就认作浏览器跳转通过。CP18本地生成页面已验证。
