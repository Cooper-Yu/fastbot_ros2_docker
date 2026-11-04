"""Coach support: bound camera traffic independently from motion feedback."""

import io
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image
from PIL import Image as PillowImage


class CameraRelay(Node):
    def __init__(self):
        super().__init__('cp23_camera_relay')
        self.last = -float('inf')
        self.output = self.create_publisher(CompressedImage, '/fastbot_web/camera/compressed', 1)
        self.create_subscription(
            Image, '/fastbot_camera/image_raw', self.receive, qos_profile_sensor_data
        )

    def receive(self, message):
        now = time.monotonic()
        if now - self.last < 0.5:
            return
        self.last = now
        if not (0 < message.width <= 1280 and 0 < message.height <= 1280):
            return
        encoding = {
            'rgb8': ('RGB', 'RGB', 3),
            'bgr8': ('RGB', 'BGR', 3),
            'mono8': ('L', 'L', 1),
        }.get(message.encoding)
        if encoding is None:
            return
        mode, raw, channels = encoding
        if (
            message.step < message.width * channels
            or len(message.data) != message.step * message.height
        ):
            return
        if len(message.data) > 5 * 1024 * 1024:
            return
        try:
            image = PillowImage.frombytes(
                mode,
                (message.width, message.height),
                bytes(message.data),
                'raw',
                raw,
                message.step,
                1,
            )
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=70)
            payload = buffer.getvalue()
            if len(payload) > 512 * 1024:
                return
            result = CompressedImage()
            result.header = message.header
            result.format = 'jpeg'
            result.data = payload
            self.output.publish(result)
        except (ValueError, OSError) as error:
            self.get_logger().warning('Camera frame rejected: ' + str(error))


def main():
    rclpy.init()
    node = CameraRelay()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
