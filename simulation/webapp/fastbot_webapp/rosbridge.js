export const ROSBRIDGE_EVENTS = Object.freeze({
  connection: 'connection',
  error: 'error',
  status: 'status'
});

export const ROSBRIDGE_INTERFACE = Object.freeze({
  connection: 'on("connection", callback) receives {state, url, code?, reason?}; on() returns a disposer. States: connecting, connected, disconnected. No automatic reconnect or replay.',
  errors: 'on("error", callback) receives {message, error, context}; on("status", callback) receives the original rosbridge status envelope.',
  connect: 'connect(url) returns a Promise resolved after open; disconnect() clears all subscriptions and advertisements, including on unexpected loss.',
  subscribe: 'subscribe(topic, type, callback, options) requires a connected socket and returns a disposer. Callback receives (message, envelope). Options: throttle_rate, queue_length, qos.',
  qos: 'Optional qos object is forwarded unchanged to servers supporting ROS 2 QoS options. Older servers may ignore or reject it; inspect status and verify cloud map delivery.',
  advertise: 'advertise(topic, type) is idempotent for a matching type and returns the advertisement id. unadvertise(topic) removes it.',
  publish: 'publish(topic, type, message) advertises if needed and sends immediately, or throws. No offline queue. Use only adapter command topics, not final cmd_vel.'
});

export class RosbridgeClient extends EventTarget {
  constructor({ maxMessageBytes = 16 * 1024 * 1024, maxBufferedBytes = 256 * 1024, connectTimeoutMs = 10000, maxSubscriptions = 64 } = {}) {
    super();
    for (const [name, value] of Object.entries({ maxMessageBytes, maxBufferedBytes, connectTimeoutMs, maxSubscriptions })) {
      if (!Number.isSafeInteger(value) || value <= 0) {
        throw new TypeError(`${name} must be a positive safe integer`);
      }
    }
    this.maxMessageBytes = maxMessageBytes;
    this.maxBufferedBytes = maxBufferedBytes;
    this.connectTimeoutMs = connectTimeoutMs;
    this.maxSubscriptions = maxSubscriptions;
    this.socket = null;
    this.url = null;
    this.state = 'disconnected';
    this.generation = 0;
    this.sequence = 0;
    this.sessionId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    this.fragments = new Map();
    this.subscriptions = new Map();
    this.advertisements = new Map();
    this.connectTimer = null;
    this.pendingConnect = null;
    this.encoder = new TextEncoder();
  }

  get connected() {
    return this.state === 'connected' && this.socket?.readyState === WebSocket.OPEN;
  }

  on(event, callback) {
    if (!Object.values(ROSBRIDGE_EVENTS).includes(event) || typeof callback !== 'function') {
      throw new TypeError('Expected connection, error or status and a callback');
    }
    const listener = notification => callback(notification.detail);
    this.addEventListener(event, listener);
    return () => this.removeEventListener(event, listener);
  }

  emit(event, detail) {
    this.dispatchEvent(new CustomEvent(event, { detail }));
  }

  report(error, context) {
    const normalized = error instanceof Error ? error : new Error(String(error));
    this.emit('error', { message: normalized.message, error: normalized, context });
  }

  nextId(prefix) {
    this.sequence += 1;
    return `${prefix}:${this.sessionId}:${this.generation}:${this.sequence}`;
  }

  validateName(topic, type) {
    if (typeof topic !== 'string' || !/^\/(?:[A-Za-z_][A-Za-z0-9_]*)(?:\/[A-Za-z_][A-Za-z0-9_]*)*$/.test(topic) || topic.length > 512) {
      throw new TypeError('Topic must be an absolute ROS topic name without trailing slash');
    }
    if (typeof type !== 'string' || !/^[A-Za-z_][A-Za-z0-9_]*\/(?:msg\/)?[A-Za-z_][A-Za-z0-9_]*$/.test(type)) {
      throw new TypeError('Expected a ROS message type such as geometry_msgs/msg/Twist');
    }
  }

  connect(address) {
    if (this.state !== 'disconnected' || this.socket !== null) {
      return Promise.reject(new Error('Disconnect the current session before connecting again'));
    }
    let parsed;
    try {
      if (typeof address !== 'string' || !address.trim()) {
        throw new TypeError('Enter the current session ROSbridge URL explicitly');
      }
      parsed = new URL(address.trim());
      if (!['ws:', 'wss:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.hash) {
        throw new TypeError('Use a ws:// or wss:// URL without embedded credentials or fragment');
      }
      if (globalThis.location?.protocol === 'https:' && parsed.protocol !== 'wss:') {
        throw new TypeError('An HTTPS dashboard requires a secure wss:// ROSbridge URL');
      }
    } catch (error) {
      this.report(error, 'connect');
      return Promise.reject(error);
    }
    let socket;
    try {
      socket = new WebSocket(parsed.href);
    } catch (error) {
      this.report(error, 'connect');
      return Promise.reject(error);
    }
    const generation = ++this.generation;
    this.socket = socket;
    this.url = parsed.href;
    this.state = 'connecting';
    const completion = new Promise((resolve, reject) => {
      this.pendingConnect = { resolve, reject };
    });
    const current = () => this.socket === socket && this.generation === generation;
    socket.onopen = () => {
      if (!current()) return;
      clearTimeout(this.connectTimer);
      this.connectTimer = null;
      const pending = this.pendingConnect;
      this.pendingConnect = null;
      this.state = 'connected';
      pending?.resolve(this);
      this.emit('connection', { state: 'connected', url: this.url });
    };
    socket.onmessage = event => {
      if (current() && this.connected) this.receive(event.data);
    };
    socket.onerror = () => {
      if (!current()) return;
      const error = new Error('ROSbridge WebSocket failed; check the current session URL, TLS and server');
      this.terminate(error, 1000, 'Transport error');
      this.report(error, 'websocket');
    };
    socket.onclose = event => {
      if (!current()) return;
      const error = new Error(`ROSbridge disconnected (${event.code}): ${event.reason || 'connection closed'}`);
      this.terminate(error, event.code, event.reason || 'Connection closed');
      if (!event.wasClean) this.report(error, 'websocket');
    };
    this.connectTimer = setTimeout(() => {
      if (!current() || this.state !== 'connecting') return;
      const error = new Error('ROSbridge connection timed out');
      this.terminate(error, 1000, 'Connection timeout');
      this.report(error, 'connect');
    }, this.connectTimeoutMs);
    this.emit('connection', { state: 'connecting', url: this.url });
    return completion;
  }

  terminate(error, code, reason) {
    const socket = this.socket;
    const previousState = this.state;
    clearTimeout(this.connectTimer);
    this.connectTimer = null;
    this.generation += 1;
    this.socket = null;
    this.state = 'disconnected';
    this.fragments.clear();
    this.subscriptions.clear();
    this.advertisements.clear();
    const pending = this.pendingConnect;
    this.pendingConnect = null;
    pending?.reject(error ?? new Error('Connection canceled'));
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        try {
          socket.close(1000, 'Client session ended');
        } catch (closeError) {
          this.report(closeError, 'close');
        }
      }
    }
    if (previousState !== 'disconnected') {
      this.emit('connection', { state: 'disconnected', url: this.url, code, reason });
    }
  }

  disconnect() {
    this.terminate(new Error('Disconnected by user'), 1000, 'Disconnected by user');
  }

  requireConnected() {
    if (!this.connected) {
      throw new Error('ROSbridge is disconnected; messages are never queued for replay');
    }
  }

  send(envelope) {
    this.requireConnected();
    let serialized;
    try {
      serialized = JSON.stringify(envelope, (key, value) => {
        if (typeof value === 'number' && !Number.isFinite(value)) {
          throw new TypeError('Nonfinite ROS values cannot be sent');
        }
        return value;
      });
    } catch (error) {
      this.report(error, 'serialize');
      throw error;
    }
    const byteLength = this.encoder.encode(serialized).byteLength;
    if (byteLength > this.maxMessageBytes) {
      throw new RangeError('Outgoing ROSbridge message exceeds configured size limit');
    }
    if (this.socket.bufferedAmount + byteLength > this.maxBufferedBytes) {
      const error = new Error('ROSbridge backpressure limit exceeded; session closed without replay');
      this.terminate(error, 1000, 'Backpressure');
      this.report(error, 'send');
      throw error;
    }
    try {
      this.socket.send(serialized);
    } catch (error) {
      this.terminate(error, 1000, 'Send failed');
      this.report(error, 'send');
      throw error;
    }
  }

  subscribe(topic, type, callback, options = {}) {
    this.validateName(topic, type);
    this.requireConnected();
    if (typeof callback !== 'function') throw new TypeError('Subscription callback is required');
    if (!options || typeof options !== 'object' || Array.isArray(options)) throw new TypeError('Invalid subscription options');
    for (const key of Object.keys(options)) {
      if (!['throttle_rate', 'queue_length', 'qos'].includes(key)) throw new TypeError(`Unsupported subscription option: ${key}`);
    }
    if (this.subscriptions.size >= this.maxSubscriptions) throw new RangeError('Subscription limit reached');
    if ([...this.subscriptions.values()].some(entry => entry.topic === topic)) {
      throw new Error(`Topic already subscribed: ${topic}; share its callback rather than duplicating handlers`);
    }
    const throttleRate = options.throttle_rate ?? 0;
    const queueLength = options.queue_length ?? 1;
    if (!Number.isSafeInteger(throttleRate) || throttleRate < 0 || throttleRate > 60000) throw new RangeError('Invalid throttle_rate');
    if (!Number.isSafeInteger(queueLength) || queueLength < 1 || queueLength > 10) throw new RangeError('queue_length must be between 1 and 10');
    const envelope = {
      op: 'subscribe', id: this.nextId('subscribe'), topic, type,
      compression: 'none', throttle_rate: throttleRate, queue_length: queueLength
    };
    if (options.qos !== undefined) {
      if (!options.qos || typeof options.qos !== 'object' || Array.isArray(options.qos)) throw new TypeError('qos must be an object');
      const serializedQos = JSON.stringify(options.qos);
      if (serializedQos.length > 4096) throw new RangeError('QoS options too large');
      envelope.qos = JSON.parse(serializedQos);
    }
    const entry = { id: envelope.id, topic, type, callback };
    this.send(envelope);
    this.subscriptions.set(entry.id, entry);
    let disposed = false;
    return () => {
      if (disposed) return;
      disposed = true;
      if (this.subscriptions.get(entry.id) !== entry) return;
      this.subscriptions.delete(entry.id);
      if (this.connected) this.send({ op: 'unsubscribe', id: entry.id, topic });
    };
  }

  advertise(topic, type) {
    this.validateName(topic, type);
    this.requireConnected();
    const existing = this.advertisements.get(topic);
    if (existing) {
      if (existing.type !== type) throw new TypeError(`Advertisement type mismatch for ${topic}`);
      return existing.id;
    }
    if (this.advertisements.size >= 64) throw new RangeError('Advertisement limit reached');
    const entry = { id: this.nextId('advertise'), type };
    this.send({ op: 'advertise', id: entry.id, topic, type, latch: false, queue_size: 1 });
    this.advertisements.set(topic, entry);
    return entry.id;
  }

  unadvertise(topic) {
    const entry = this.advertisements.get(topic);
    if (!entry) return;
    this.advertisements.delete(topic);
    if (this.connected) this.send({ op: 'unadvertise', id: entry.id, topic });
  }

  publish(topic, type, message) {
    this.validateName(topic, type);
    this.requireConnected();
    if (!message || typeof message !== 'object' || Array.isArray(message)) throw new TypeError('ROS message must be an object');
    this.advertise(topic, type);
    const id = this.nextId('publish');
    this.send({ op: 'publish', id, topic, msg: message, latch: false });
    return id;
  }

  // Reassemble ROSbridge large-message fragments before dispatching publications.
  // Bounds apply to the entire pending set; incomplete groups expire after 5 seconds.
  receiveFragment(packet) {
    const now = performance.now();
    for (const [id, group] of this.fragments) {
      if (now - group.started > 5000) this.fragments.delete(id);
    }
    if (typeof packet.id !== 'string' || packet.id.length > 512 ||
        !Number.isSafeInteger(packet.total) || packet.total < 1 || packet.total > 4096 ||
        !Number.isSafeInteger(packet.num) || packet.num < 0 || packet.num >= packet.total ||
        typeof packet.data !== 'string') throw new TypeError('Invalid ROSbridge fragment');
    let group = this.fragments.get(packet.id);
    if (!group) {
      if (this.fragments.size >= 8) {
        this.fragments.delete(this.fragments.keys().next().value);
        this.emit('status', {level: 'warning', msg: 'Incomplete large frame dropped; waiting for the next frame'});
      }
      group = { total: packet.total, chunks: new Map(), bytes: 0, started: now };
      this.fragments.set(packet.id, group);
    }
    if (group.total !== packet.total) throw new TypeError('Fragment count changed');
    if (group.chunks.has(packet.num)) {
      if (group.chunks.get(packet.num) !== packet.data) throw new TypeError('Conflicting duplicate fragment');
      return;
    }
    group.bytes += this.encoder.encode(packet.data).byteLength;
    if (group.bytes > this.maxMessageBytes ||
        [...this.fragments.values()].reduce((sum, value) => sum + value.bytes, 0) > this.maxMessageBytes * 2) {
      throw new RangeError('Fragment assembly size limit exceeded');
    }
    group.chunks.set(packet.num, packet.data);
    if (group.chunks.size === group.total) {
      const data = Array.from({ length: group.total }, (_, index) => group.chunks.get(index)).join('');
      this.fragments.delete(packet.id);
      this.receive(data, true);
    }
  }

  receive(data, assembled = false) {
    try {
      if (typeof data !== 'string') throw new TypeError('Expected JSON text; binary/CBOR transport was not requested');
      if (data.length > this.maxMessageBytes || this.encoder.encode(data).byteLength > this.maxMessageBytes) {
        throw new RangeError('Incoming ROSbridge message exceeds configured size limit');
      }
      const envelope = JSON.parse(data);
      if (!envelope || typeof envelope !== 'object' || Array.isArray(envelope)) throw new TypeError('Malformed ROSbridge envelope');
      if (envelope.op === 'fragment') {
        if (assembled) throw new TypeError('Nested fragments are unsupported');
        this.receiveFragment(envelope);
        return;
      }
      if (envelope.op === 'status') {
        if (envelope.level === 'error' || envelope.level === 'fatal') {
          const entry = this.subscriptions.get(envelope.id);
          if (entry) this.subscriptions.delete(entry.id);
          for (const [topic, advertisement] of this.advertisements) {
            if (advertisement.id === envelope.id) this.advertisements.delete(topic);
          }
          this.report(new Error(String(envelope.msg ?? 'ROSbridge protocol error')), { op: 'status', id: envelope.id, level: envelope.level });
        }
        this.emit('status', envelope);
        return;
      }
      if (envelope.op !== 'publish') {
        this.report(new Error(`Unsupported ROSbridge operation: ${String(envelope.op)}`), 'receive');
        return;
      }
      if (typeof envelope.topic !== 'string' || !envelope.msg || typeof envelope.msg !== 'object' || Array.isArray(envelope.msg)) {
        throw new TypeError('Malformed ROSbridge publication');
      }
      const entry = [...this.subscriptions.values()].find(subscription => subscription.topic === envelope.topic);
      if (!entry) return;
      if (envelope.id !== undefined && envelope.id !== entry.id) return;
      try {
        entry.callback(envelope.msg, envelope);
      } catch (error) {
        this.report(error, { op: 'callback', topic: entry.topic });
      }
    } catch (error) {
      this.terminate(error, 1000, 'Invalid protocol data');
      this.report(error, 'receive');
    }
  }
}
