# serial_motor_msgs 当前流程

```mermaid
flowchart LR
  A[三个msg定义] --> B[rosidl_generate_interfaces]
  B --> C[生成并安装类型支持]
  C --> D[serial_motor导入消息]
  D --> E[累计计数与轮速发布]
```

该包只定义消息契约；使用它的节点才执行通信和发布。生成/导入证据与实际ROS使用证据分别保存在训练记录中。
