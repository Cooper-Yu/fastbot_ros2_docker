(() => {
  'use strict';
  const TOPICS = Object.freeze({
    map: '/map', pose: '/web_nav/pose', status: '/web_nav/status',
    // Coach support (CP23-C023): 使用当前仿真已验证的里程计话题。
    odom: '/fastbot/odom', camera: '/fastbot_1/camera/image',
    goal: '/web_nav/goal', cancel: '/web_nav/cancel',
    manual: '/web/manual_cmd', initialPose: '/initialpose'
  });
  const INPUTS = [
    [TOPICS.map, 'nav_msgs/msg/OccupancyGrid', 1000],
    [TOPICS.pose, 'geometry_msgs/msg/PoseStamped', 100],
    [TOPICS.status, 'std_msgs/msg/String', 0],
    [TOPICS.odom, 'nav_msgs/msg/Odometry', 100],
    [TOPICS.camera, 'sensor_msgs/msg/Image', 500]
  ];
  const OUTPUTS = new Map([
    [TOPICS.goal, 'geometry_msgs/msg/PoseStamped'],
    [TOPICS.cancel, 'std_msgs/msg/Empty'],
    [TOPICS.manual, 'geometry_msgs/msg/Twist'],
    [TOPICS.initialPose, 'geometry_msgs/msg/PoseWithCovarianceStamped']
  ]);
  const zeroTwist = () => ({linear: {x: 0, y: 0, z: 0}, angular: {x: 0, y: 0, z: 0}});
  class Rosbridge extends EventTarget {
    constructor() {
      super();
      this.socket = null;
      this.state = 'disconnected';
      this.sequence = 0;
      this.generation = 0;
      this.manualLive = false;
      this.openTimer = null;
    }
    emit(type, detail) { this.dispatchEvent(new CustomEvent(type, {detail})); }
    setState(state) { this.state = state; this.emit('state', {state}); }
    get connected() { return this.state === 'connected' && this.socket?.readyState === WebSocket.OPEN; }
    connect(address = 'ws://127.0.0.1:9226') {
      if (this.state !== 'disconnected') throw new Error('Disconnect before connecting again');
      const url = new URL(address);
      if (!['ws:', 'wss:'].includes(url.protocol) ||
          !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) ||
          url.username || url.password || url.search || url.hash || url.pathname !== '/') {
        throw new Error('Only a loopback ROSbridge root URL is allowed');
      }
      const socket = new WebSocket(url.href);
      const generation = ++this.generation;
      this.socket = socket;
      this.setState('connecting');
      const current = () => this.socket === socket && this.generation === generation;
      this.openTimer = setTimeout(() => {
        if (current()) { this.emit('error', {message: 'Connection timeout'}); this.disconnect(); }
      }, 8000);
      socket.onopen = () => {
        if (!current()) return;
        clearTimeout(this.openTimer);
        try {
          for (const [topic, type] of OUTPUTS) this.send({op: 'advertise', topic, type, queue_size: 1});
          for (const [topic, type, throttle] of INPUTS) {
            const request = {op: 'subscribe', id: `sub:${topic}`, topic, type,
              throttle_rate: throttle, queue_length: 1, compression: 'none'};
            if (topic === TOPICS.map) request.qos = {
              durability: 'transient_local', reliability: 'reliable', history: 'keep_last', depth: 1
            };
            this.send(request);
          }
          this.setState('connected');
        } catch (error) {
          this.emit('error', {message: error.message});
          this.disconnect();
        }
      };
      socket.onmessage = event => {
        if (!current() || !this.connected) return;
        try {
          if (typeof event.data !== 'string' || event.data.length > 12000000) {
            throw new Error('Unsupported binary or oversized ROSbridge frame');
          }
          const packet = JSON.parse(event.data);
          if (!packet || typeof packet !== 'object') throw new Error('Invalid ROSbridge packet');
          if (packet.op === 'status') { this.emit('bridge-status', packet); return; }
          if (packet.op !== 'publish' || !INPUTS.some(([topic]) => topic === packet.topic)) return;
          if (!packet.msg || typeof packet.msg !== 'object' || Array.isArray(packet.msg)) {
            throw new Error('Invalid ROS message envelope');
          }
          this.emit('message', {topic: packet.topic, msg: packet.msg, receivedAt: performance.now()});
        } catch (error) { this.emit('error', {message: error.message}); }
      };
      socket.onerror = () => {
        if (!current()) return;
        this.emit('error', {message: 'WebSocket failure; no automatic reconnect'});
        this.disconnect();
      };
      socket.onclose = event => {
        if (!current()) return;
        clearTimeout(this.openTimer);
        this.socket = null;
        this.manualLive = false;
        this.setState('disconnected');
        this.emit('closed', {code: event.code, reason: event.reason, intentional: false});
      };
    }
    send(packet) {
      if (this.socket?.readyState !== WebSocket.OPEN) throw new Error('ROSbridge is not open');
      if (this.socket.bufferedAmount > 65536) throw new Error('ROSbridge backpressure; command not queued');
      this.socket.send(JSON.stringify(packet));
    }
    publish(topic, msg) {
      if (!this.connected) throw new Error('Not connected; commands are never buffered');
      if (!OUTPUTS.has(topic)) throw new Error('Publishing outside the web adapter interface is forbidden');
      if (!msg || typeof msg !== 'object' || Array.isArray(msg)) throw new Error('Expected ROS message object');
      if (topic === TOPICS.manual) {
        const linear = msg.linear?.x, angular = msg.angular?.z;
        if (!Number.isFinite(linear) || !Number.isFinite(angular)) throw new Error('Nonfinite manual command');
        msg = zeroTwist();
        msg.linear.x = Math.max(-0.15, Math.min(0.15, linear));
        msg.angular.z = Math.max(-0.6, Math.min(0.6, angular));
        this.send({op: 'publish', id: `pub:${++this.sequence}`, topic, msg});
        this.manualLive = Boolean(msg.linear.x || msg.angular.z);
        return;
      }
      if (topic === TOPICS.cancel) msg = {};
      this.send({op: 'publish', id: `pub:${++this.sequence}`, topic, msg});
    }
    stopManual() {
      if (this.connected && this.manualLive) this.publish(TOPICS.manual, zeroTwist());
    }
    disconnect() {
      if (!this.socket) return;
      this.emit('before-disconnect', {});
      try { this.stopManual(); }
      catch (error) { this.emit('error', {message: `Zero not delivered: ${error.message}; watchdog required`}); }
      const socket = this.socket;
      clearTimeout(this.openTimer);
      ++this.generation;
      this.socket = null;
      this.manualLive = false;
      socket.close(1000, 'User disconnect');
      this.setState('disconnected');
      this.emit('closed', {code: 1000, reason: 'User disconnect', intentional: true});
    }
  }
  window.FastBotBridge = Object.freeze({Rosbridge, TOPICS, zeroTwist});
})();
