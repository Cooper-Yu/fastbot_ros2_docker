export const RENDERER_INTERFACE = Object.freeze({
  common: 'Construct with (canvas, {onStatus(text, state), onError(error), statusElement, mapFrame}). Status callbacks are optional. clear() removes received data, dispose() releases resources. Invalid updates report and throw; no synthetic sensor content is generated.',
  map: 'MapRenderer.update(OccupancyGrid), updateMap(OccupancyGrid), updatePose(PoseStamped|null), resize(). Map is retained until clear(), including across pose updates. Pose header.frame_id must match the received map and configured mapFrame.',
  camera: 'CameraRenderer.update(sensor_msgs/Image), updateImage(message), resize(). Supports rgb8, bgr8, mono8 with array, Uint8Array or base64 data and padded rows. clear() removes the last image; freshness is managed by app.js.',
  robot: 'RobotRenderer.ready is a Promise for URDF and all visual meshes. update(PoseStamped) and updatePose(PoseStamped|null) use actual map pose. updateJointState(sensor_msgs/JointState) optionally supplies measured joint positions. clear() hides the robot but retains loaded assets. Default URDF URL is ./assets/fastbot.urdf relative to document.baseURI.',
  view: 'RobotRenderer follows actual measured pose over a fixed metric reference grid by default; the grid is not an environment map. setFollowView(span) selects measured-pose tracking. setView({center:[x,y,z], span:meters}) selects a fixed view. Translation remains visible; configure a whole-home span in cloud if necessary.',
  assets: 'Only URDF visual meshes are rendered. Link/joint/visual transforms and mesh scales are preserved. STL binary/ASCII and COLLADA triangles/polylist/polygons/trifans/tristrips, source accessors, materials, scene instances, unit and up_axis are supported. An explicit URDF material overrides embedded mesh materials. Otherwise unsupported geometry or textures produce explicit errors, not replacement meshes. Unmeasured movable joints remain at URDF zero, not invented animation.'
});

const MAX_PIXELS = 16 * 1024 * 1024;
const MAX_VERTICES = 6000000;
const MAX_RESOURCE_BYTES = 128 * 1024 * 1024;
const EPSILON = 1e-10;

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function numberList(text, expected) {
  const values = String(text ?? '').trim().split(/\s+/).filter(Boolean).map(Number);
  requireCondition(values.every(Number.isFinite), 'Invalid numeric asset data');
  if (expected !== undefined) requireCondition(values.length === expected, `Expected ${expected} numbers`);
  return values;
}

function integer(value, name, minimum = 0) {
  const parsed = Number(value);
  requireCondition(Number.isSafeInteger(parsed) && parsed >= minimum, `Invalid ${name}`);
  return parsed;
}

function children(element, name) {
  return Array.from(element?.children ?? []).filter(child => child.localName === name);
}

function child(element, name) {
  return children(element, name)[0] ?? null;
}

function descendants(element, name) {
  return Array.from(element.getElementsByTagName('*')).filter(node => node.localName === name);
}

function parseXml(text, label) {
  requireCondition(!/<!DOCTYPE|<!ENTITY/i.test(text), `${label}: external declarations are not supported`);
  const document = new DOMParser().parseFromString(text, 'application/xml');
  requireCondition(!descendants(document, 'parsererror').length, `${label}: malformed XML`);
  return document;
}

function identity() {
  return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
}

function multiply(left, right) {
  const output = new Array(16).fill(0);
  for (let column = 0; column < 4; column += 1) {
    for (let row = 0; row < 4; row += 1) {
      for (let inner = 0; inner < 4; inner += 1) {
        output[column * 4 + row] += left[inner * 4 + row] * right[column * 4 + inner];
      }
    }
  }
  return output;
}

function translation(values) {
  const matrix = identity();
  matrix[12] = values[0];
  matrix[13] = values[1];
  matrix[14] = values[2];
  return matrix;
}

function scaling(values) {
  const matrix = identity();
  matrix[0] = values[0];
  matrix[5] = values[1];
  matrix[10] = values[2];
  return matrix;
}

function subtract(left, right) {
  return left.map((value, index) => value - right[index]);
}

function cross(left, right) {
  return [left[1] * right[2] - left[2] * right[1], left[2] * right[0] - left[0] * right[2], left[0] * right[1] - left[1] * right[0]];
}

function dot(left, right) {
  return left.reduce((sum, value, index) => sum + value * right[index], 0);
}

function normalized(values) {
  const length = Math.hypot(...values);
  requireCondition(Number.isFinite(length) && length > EPSILON, 'Zero or invalid direction');
  return values.map(value => value / length);
}

function rotation(axis, angle) {
  const [axisX, axisY, axisZ] = normalized(axis);
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  const complement = 1 - cosine;
  return [
    cosine + axisX * axisX * complement, axisY * axisX * complement + axisZ * sine, axisZ * axisX * complement - axisY * sine, 0,
    axisX * axisY * complement - axisZ * sine, cosine + axisY * axisY * complement, axisZ * axisY * complement + axisX * sine, 0,
    axisX * axisZ * complement + axisY * sine, axisY * axisZ * complement - axisX * sine, cosine + axisZ * axisZ * complement, 0,
    0, 0, 0, 1
  ];
}

function originMatrix(origin) {
  const position = numberList(origin?.getAttribute('xyz') ?? '0 0 0', 3);
  const angles = numberList(origin?.getAttribute('rpy') ?? '0 0 0', 3);
  return multiply(translation(position), multiply(rotation([0, 0, 1], angles[2]), multiply(rotation([0, 1, 0], angles[1]), rotation([1, 0, 0], angles[0]))));
}

function poseMatrix(pose) {
  requireCondition(pose?.position && pose?.orientation, 'Missing position or quaternion');
  const position = [pose.position.x, pose.position.y, pose.position.z];
  const quaternion = [pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w];
  requireCondition([...position, ...quaternion].every(value => typeof value === 'number' && Number.isFinite(value)), 'Nonfinite pose');
  const [quatX, quatY, quatZ, quatW] = normalized(quaternion);
  return [
    1 - 2 * (quatY * quatY + quatZ * quatZ), 2 * (quatX * quatY + quatZ * quatW), 2 * (quatX * quatZ - quatY * quatW), 0,
    2 * (quatX * quatY - quatZ * quatW), 1 - 2 * (quatX * quatX + quatZ * quatZ), 2 * (quatY * quatZ + quatX * quatW), 0,
    2 * (quatX * quatZ + quatY * quatW), 2 * (quatY * quatZ - quatX * quatW), 1 - 2 * (quatX * quatX + quatY * quatY), 0,
    ...position, 1
  ];
}

function point(matrix, values) {
  return [0, 1, 2].map(row => matrix[row] * values[0] + matrix[4 + row] * values[1] + matrix[8 + row] * values[2] + matrix[12 + row]);
}

function normalMatrix(matrix) {
  const first = [matrix[0], matrix[1], matrix[2]];
  const second = [matrix[4], matrix[5], matrix[6]];
  const third = [matrix[8], matrix[9], matrix[10]];
  const firstCofactor = cross(second, third);
  const determinant = dot(first, firstCofactor);
  requireCondition(Math.abs(determinant) > EPSILON, 'Singular visual transform');
  return [...firstCofactor, ...cross(third, first), ...cross(first, second)].map(value => value / determinant);
}

function checkedPose(message, mapFrame) {
  requireCondition(message?.header?.frame_id === mapFrame, `Expected measured pose in ${mapFrame}`);
  return poseMatrix(message.pose);
}

class Reporter {
  constructor(canvas, options = {}) {
    requireCondition(canvas && typeof canvas.getContext === 'function', 'A canvas element is required');
    this.canvas = canvas;
    this.options = options;
    this.disposed = false;
    this.mapFrame = options.mapFrame ?? 'map';
  }

  status(text, state = 'ready') {
    if (this.disposed) return;
    if (this.options.statusElement) {
      this.options.statusElement.textContent = text;
      this.options.statusElement.dataset.state = state;
    }
    this.canvas.dataset.rendererState = state;
    this.canvas.dataset.rendererStatus = text;
    this.options.onStatus?.(text, state);
  }

  fail(error) {
    const normalizedError = error instanceof Error ? error : new Error(String(error));
    this.status(normalizedError.message, 'error');
    this.options.onError?.(normalizedError);
    return normalizedError;
  }

  check() {
    requireCondition(!this.disposed, 'Renderer has been disposed');
  }

  observeResize() {
    if (typeof ResizeObserver === 'function') {
      this.observer = new ResizeObserver(() => {
        if (!this.disposed) this.resize();
      });
      this.observer.observe(this.canvas);
    } else {
      this.resizeListener = () => { if (!this.disposed) this.resize(); };
      globalThis.addEventListener('resize', this.resizeListener);
    }
  }

  resizeSurface() {
    const rectangle = this.canvas.getBoundingClientRect();
    const ratio = Math.min(globalThis.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.round(rectangle.width * ratio));
    const height = Math.max(1, Math.round(rectangle.height * ratio));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
  }

  dispose() {
    if (this.disposed) return;
    this.observer?.disconnect();
    if (this.resizeListener) globalThis.removeEventListener('resize', this.resizeListener);
    this.disposed = true;
  }
}

export class MapRenderer extends Reporter {
  constructor(canvas, options = {}) {
    super(canvas, options);
    this.context = canvas.getContext('2d');
    requireCondition(this.context, 'Canvas 2D is unavailable for the map');
    this.surface = document.createElement('canvas');
    this.surfaceContext = this.surface.getContext('2d');
    requireCondition(this.surfaceContext, 'Cannot allocate occupancy raster');
    this.grid = null;
    this.pose = null;
    this.observeResize();
    this.resize();
    this.status('No map received', 'unavailable');
  }

  update(message) {
    return this.updateMap(message);
  }

  updateMap(message) {
    this.check();
    try {
      const width = integer(message?.info?.width, 'map width', 1);
      const height = integer(message?.info?.height, 'map height', 1);
      const resolution = message.info.resolution;
      requireCondition(width * height <= MAX_PIXELS, 'OccupancyGrid exceeds raster limit');
      requireCondition(typeof resolution === 'number' && Number.isFinite(resolution) && resolution > 0, 'Invalid map resolution');
      requireCondition(message.header?.frame_id === this.mapFrame, `Map frame must be ${this.mapFrame}`);
      requireCondition(message.data && message.data.length === width * height, 'OccupancyGrid data length mismatch');
      const transform = poseMatrix(message.info.origin);
      requireCondition(Math.abs(transform[0] * transform[5] - transform[1] * transform[4]) > EPSILON, 'Map origin projects to a degenerate plane');
      const raster = this.surfaceContext.createImageData(width, height);
      for (let index = 0; index < width * height; index += 1) {
        let occupancy = message.data[index];
        if (occupancy === 255 && message.data instanceof Uint8Array) occupancy = -1;
        requireCondition(Number.isInteger(occupancy) && occupancy >= -1 && occupancy <= 100, 'Invalid occupancy value');
        const shade = occupancy < 0 ? 112 : Math.round(247 - occupancy * 2.25);
        const offset = index * 4;
        raster.data[offset] = shade;
        raster.data[offset + 1] = occupancy < 0 ? 126 : shade;
        raster.data[offset + 2] = occupancy < 0 ? 145 : shade;
        raster.data[offset + 3] = 255;
      }
      this.surface.width = width;
      this.surface.height = height;
      this.surfaceContext.putImageData(raster, 0, 0);
      this.grid = { width, height, resolution, transform };
      this.draw();
      this.status(`${width} × ${height} · ${resolution.toFixed(3)} m/cell · OccupancyGrid`, 'ready');
    } catch (error) {
      throw this.fail(error);
    }
  }

  updatePose(message) {
    this.check();
    try {
      this.pose = message === null ? null : checkedPose(message, this.mapFrame);
      this.draw();
    } catch (error) {
      this.pose = null;
      this.draw();
      throw this.fail(error);
    }
  }

  resize() {
    this.resizeSurface();
    this.draw();
  }

  draw() {
    const context = this.context;
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (!this.grid) return;
    const { width, height, resolution, transform } = this.grid;
    const corners = [[0, 0, 0], [width * resolution, 0, 0], [0, height * resolution, 0], [width * resolution, height * resolution, 0]].map(corner => point(transform, corner));
    const minimumX = Math.min(...corners.map(corner => corner[0]));
    const maximumX = Math.max(...corners.map(corner => corner[0]));
    const minimumY = Math.min(...corners.map(corner => corner[1]));
    const maximumY = Math.max(...corners.map(corner => corner[1]));
    const padding = Math.min(24, Math.min(this.canvas.width, this.canvas.height) * 0.08);
    const scale = Math.max(EPSILON, Math.min((this.canvas.width - padding * 2) / Math.max(maximumX - minimumX, EPSILON), (this.canvas.height - padding * 2) / Math.max(maximumY - minimumY, EPSILON)));
    const centerX = (minimumX + maximumX) / 2;
    const centerY = (minimumY + maximumY) / 2;
    const screenX = worldX => this.canvas.width / 2 + (worldX - centerX) * scale;
    const screenY = worldY => this.canvas.height / 2 - (worldY - centerY) * scale;
    context.imageSmoothingEnabled = false;
    context.setTransform(scale * transform[0] * resolution, -scale * transform[1] * resolution, scale * transform[4] * resolution, -scale * transform[5] * resolution, screenX(transform[12]), screenY(transform[13]));
    context.drawImage(this.surface, 0, 0);
    context.setTransform(1, 0, 0, 1, 0, 0);
    if (this.pose) {
      const pose = this.pose;
      const yaw = Math.atan2(pose[1], pose[0]);
      const markerSize = Math.max(7, Math.min(18, 0.16 * scale));
      context.save();
      context.translate(screenX(pose[12]), screenY(pose[13]));
      context.rotate(-yaw);
      context.beginPath();
      context.moveTo(markerSize, 0);
      context.lineTo(-markerSize * 0.65, -markerSize * 0.6);
      context.lineTo(-markerSize * 0.35, 0);
      context.lineTo(-markerSize * 0.65, markerSize * 0.6);
      context.closePath();
      context.fillStyle = '#16c7aa';
      context.strokeStyle = '#062d2b';
      context.lineWidth = 2;
      context.fill();
      context.stroke();
      context.restore();
    }
  }

  clear() {
    this.check();
    this.grid = null;
    this.pose = null;
    this.surface.width = 1;
    this.surface.height = 1;
    this.draw();
    this.status('No map received', 'unavailable');
  }

  dispose() {
    if (this.disposed) return;
    this.clear();
    super.dispose();
  }
}

function imageBytes(data, maximum) {
  if (typeof data === 'string') {
    requireCondition(data.length <= Math.ceil(maximum / 3) * 4 + 4, 'Camera base64 exceeds buffer limit');
    const decoded = atob(data);
    requireCondition(decoded.length <= maximum, 'Camera data exceeds buffer limit');
    return Uint8Array.from(decoded, character => character.charCodeAt(0));
  }
  if (data instanceof Uint8Array) {
    requireCondition(data.length <= maximum, 'Camera data exceeds buffer limit');
    return data;
  }
  requireCondition(Array.isArray(data) && data.length <= maximum, 'Expected image byte array or base64');
  requireCondition(data.every(value => Number.isInteger(value) && value >= 0 && value <= 255), 'Invalid camera byte value');
  return Uint8Array.from(data);
}

export class CameraRenderer extends Reporter {
  constructor(canvas, options = {}) {
    super(canvas, options);
    this.context = canvas.getContext('2d');
    requireCondition(this.context, 'Canvas 2D is unavailable for the camera');
    this.surface = document.createElement('canvas');
    this.surfaceContext = this.surface.getContext('2d');
    requireCondition(this.surfaceContext, 'Cannot allocate camera raster');
    this.hasImage = false;
    this.observeResize();
    this.resize();
    this.status('No image received', 'unavailable');
  }

  update(message) {
    return this.updateImage(message);
  }

  async updateCompressed(message) {
    this.check();
    const generation = (this.compressedGeneration ?? 0) + 1;
    this.compressedGeneration = generation;
    requireCondition(['jpeg', 'jpg', 'png'].includes(String(message.format).toLowerCase()), 'Unsupported compressed camera format');
    const bytes = imageBytes(message.data, 512 * 1024);
    const bitmap = await createImageBitmap(new Blob([bytes], {type: message.format === 'png' ? 'image/png' : 'image/jpeg'}));
    try {
      if (this.disposed || generation !== this.compressedGeneration) return;
      requireCondition(bitmap.width > 0 && bitmap.height > 0 && bitmap.width <= 1280 && bitmap.height <= 1280, 'Compressed camera dimensions exceed limit');
      this.surface.width = bitmap.width; this.surface.height = bitmap.height;
      this.surfaceContext.drawImage(bitmap, 0, 0);
      this.hasImage = true; this.draw();
      this.status(bitmap.width + ' × ' + bitmap.height + ' · JPEG · 2 Hz', 'fresh');
    } finally { bitmap.close(); }
  }

  updateImage(message) {
    this.check();
    try {
      const width = integer(message?.width, 'camera width', 1);
      const height = integer(message?.height, 'camera height', 1);
      requireCondition(width * height <= MAX_PIXELS, 'Camera image exceeds raster limit');
      const encoding = String(message.encoding).toLowerCase();
      requireCondition(['rgb8', 'bgr8', 'mono8'].includes(encoding), `Unsupported camera encoding: ${encoding}`);
      const channels = encoding === 'mono8' ? 1 : 3;
      const step = integer(message.step, 'camera row step', width * channels);
      const required = step * height;
      requireCondition(Number.isSafeInteger(required) && required <= MAX_RESOURCE_BYTES, 'Camera row buffer exceeds limit');
      const bytes = imageBytes(message.data, MAX_RESOURCE_BYTES);
      requireCondition(bytes.length === required, 'Camera buffer must contain height × step bytes');
      const raster = this.surfaceContext.createImageData(width, height);
      for (let row = 0; row < height; row += 1) {
        for (let column = 0; column < width; column += 1) {
          const sourceOffset = row * step + column * channels;
          const targetOffset = (row * width + column) * 4;
          raster.data[targetOffset] = bytes[sourceOffset + (encoding === 'bgr8' ? 2 : 0)];
          raster.data[targetOffset + 1] = bytes[sourceOffset + (channels === 1 ? 0 : 1)];
          raster.data[targetOffset + 2] = bytes[sourceOffset + (encoding === 'rgb8' ? 2 : 0)];
          raster.data[targetOffset + 3] = 255;
        }
      }
      this.surface.width = width;
      this.surface.height = height;
      this.surfaceContext.putImageData(raster, 0, 0);
      this.hasImage = true;
      this.draw();
      this.status(`${width} × ${height} · ${encoding}`, 'fresh');
    } catch (error) {
      this.hasImage = false;
      this.draw();
      throw this.fail(error);
    }
  }

  resize() {
    this.resizeSurface();
    this.draw();
  }

  draw() {
    const context = this.context;
    context.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (!this.hasImage) return;
    const scale = Math.min(this.canvas.width / this.surface.width, this.canvas.height / this.surface.height);
    const width = this.surface.width * scale;
    const height = this.surface.height * scale;
    context.drawImage(this.surface, (this.canvas.width - width) / 2, (this.canvas.height - height) / 2, width, height);
  }

  clear() {
    this.check();
    this.compressedGeneration = (this.compressedGeneration ?? 0) + 1;
    this.hasImage = false;
    this.surface.width = 1;
    this.surface.height = 1;
    this.draw();
    this.status('No image received', 'unavailable');
  }

  dispose() {
    if (this.disposed) return;
    this.clear();
    super.dispose();
  }
}

function makeGeometry() {
  return { positions: [], normals: [], colors: [] };
}

function appendTriangle(geometry, vertices, colors = null) {
  requireCondition(geometry.positions.length / 3 + 3 <= MAX_VERTICES, 'Mesh exceeds vertex limit');
  requireCondition(vertices.flat().every(Number.isFinite), 'Nonfinite mesh vertex');
  const normal = cross(subtract(vertices[1], vertices[0]), subtract(vertices[2], vertices[0]));
  const length = Math.hypot(...normal);
  if (length <= EPSILON * EPSILON) return;
  const unitNormal = normal.map(value => value / length);
  for (let index = 0; index < 3; index += 1) {
    geometry.positions.push(...vertices[index]);
    geometry.normals.push(...unitNormal);
    geometry.colors.push(...(colors?.[index] ?? [1, 1, 1, 1]));
  }
}

function parseStl(buffer) {
  const geometry = makeGeometry();
  const view = new DataView(buffer);
  if (buffer.byteLength >= 84) {
    const count = view.getUint32(80, true);
    if (84 + count * 50 === buffer.byteLength) {
      requireCondition(count <= MAX_VERTICES / 3, 'Binary STL exceeds triangle limit');
      for (let face = 0; face < count; face += 1) {
        const vertices = [];
        for (let vertex = 0; vertex < 3; vertex += 1) {
          const offset = 84 + face * 50 + 12 + vertex * 12;
          vertices.push([view.getFloat32(offset, true), view.getFloat32(offset + 4, true), view.getFloat32(offset + 8, true)]);
        }
        appendTriangle(geometry, vertices);
      }
      requireCondition(geometry.positions.length > 0, 'Empty binary STL');
      return [{ geometry, color: null }];
    }
  }
  const text = new TextDecoder().decode(buffer);
  requireCondition(/^\s*solid\b/i.test(text), 'Invalid binary or ASCII STL');
  const facets = text.matchAll(/facet\s+normal\s+[^\r\n]+\s+outer\s+loop([\s\S]*?)endloop\s+endfacet/gi);
  let faceCount = 0;
  for (const facet of facets) {
    const vertices = Array.from(facet[1].matchAll(/vertex\s+([^\r\n]+)/gi), match => numberList(match[1], 3));
    requireCondition(vertices.length === 3, 'Malformed ASCII STL facet');
    appendTriangle(geometry, vertices);
    faceCount += 1;
  }
  requireCondition(faceCount > 0 && geometry.positions.length > 0, 'Empty or unsupported ASCII STL');
  return [{ geometry, color: null }];
}

function triangulatePolygon(vertices) {
  requireCondition(vertices.length >= 3 && vertices.length <= 10000, 'Invalid or oversized polygon');
  if (vertices.length === 3) return [[0, 1, 2]];
  const normal = [0, 0, 0];
  for (let index = 0; index < vertices.length; index += 1) {
    const current = vertices[index];
    const next = vertices[(index + 1) % vertices.length];
    normal[0] += (current[1] - next[1]) * (current[2] + next[2]);
    normal[1] += (current[2] - next[2]) * (current[0] + next[0]);
    normal[2] += (current[0] - next[0]) * (current[1] + next[1]);
  }
  requireCondition(Math.hypot(...normal) > EPSILON * EPSILON, 'Degenerate COLLADA polygon');
  const droppedAxis = normal.map(Math.abs).indexOf(Math.max(...normal.map(Math.abs)));
  const projected = vertices.map(vertex => vertex.filter((value, index) => index !== droppedAxis));
  const area = projected.reduce((sum, vertex, index) => {
    const next = projected[(index + 1) % projected.length];
    return sum + vertex[0] * next[1] - next[0] * vertex[1];
  }, 0);
  const direction = Math.sign(area);
  requireCondition(direction !== 0, 'Degenerate projected polygon');
  const turn = (first, second, third) => (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (third[0] - first[0]);
  const remaining = vertices.map((vertex, index) => index);
  const triangles = [];
  while (remaining.length > 3) {
    let clipped = false;
    for (let index = 0; index < remaining.length; index += 1) {
      const previous = remaining[(index + remaining.length - 1) % remaining.length];
      const current = remaining[index];
      const next = remaining[(index + 1) % remaining.length];
      const first = projected[previous];
      const second = projected[current];
      const third = projected[next];
      if (direction * turn(first, second, third) <= 0) continue;
      const contains = remaining.some(candidate => {
        if ([previous, current, next].includes(candidate)) return false;
        const test = projected[candidate];
        return direction * turn(first, second, test) >= 0 && direction * turn(second, third, test) >= 0 && direction * turn(third, first, test) >= 0;
      });
      if (contains) continue;
      triangles.push([previous, current, next]);
      remaining.splice(index, 1);
      clipped = true;
      break;
    }
    requireCondition(clipped, 'Cannot triangulate COLLADA polygon; self intersections or duplicate boundary vertices');
  }
  triangles.push([...remaining]);
  return triangles;
}

function rgba(text, fallback = null) {
  if (text === null || text === undefined) return fallback;
  const values = numberList(text);
  requireCondition(values.length === 3 || values.length === 4, 'Expected RGB or RGBA color');
  if (values.length === 3) values.push(1);
  requireCondition(values.every(value => value >= 0 && value <= 1), 'Color channel outside [0,1]');
  return values;
}

function parseCollada(buffer, overrideColor = null) {
  const document = parseXml(new TextDecoder().decode(buffer), 'COLLADA');
  requireCondition(document.documentElement.localName === 'COLLADA', 'Expected COLLADA document');
  const identifiers = new Map();
  for (const element of descendants(document, '*').length ? descendants(document, '*') : Array.from(document.getElementsByTagName('*'))) {
    const identifier = element.getAttribute('id');
    if (identifier) {
      requireCondition(!identifiers.has(identifier), `Duplicate COLLADA id: ${identifier}`);
      identifiers.set(identifier, element);
    }
  }
  const resolve = reference => {
    requireCondition(typeof reference === 'string' && reference.startsWith('#'), `External COLLADA reference not supported: ${reference}`);
    const element = identifiers.get(reference.slice(1));
    requireCondition(element, `Missing COLLADA reference: ${reference}`);
    return element;
  };
  const sourceCache = new Map();
  const readSource = reference => {
    if (sourceCache.has(reference)) return sourceCache.get(reference);
    const source = resolve(reference);
    requireCondition(source.localName === 'source', 'Expected COLLADA source');
    const accessor = child(child(source, 'technique_common'), 'accessor');
    requireCondition(accessor, 'COLLADA source has no accessor');
    const array = resolve(accessor.getAttribute('source'));
    requireCondition(array.localName === 'float_array', 'Only numeric COLLADA source arrays are supported');
    const values = numberList(array.textContent);
    requireCondition(values.length === integer(array.getAttribute('count'), 'float_array count'), 'COLLADA float_array count mismatch');
    const stride = integer(accessor.getAttribute('stride') ?? 1, 'accessor stride', 1);
    const offset = integer(accessor.getAttribute('offset') ?? 0, 'accessor offset');
    const count = integer(accessor.getAttribute('count'), 'accessor count');
    const parameters = children(accessor, 'param');
    const slots = parameters.map((parameter, index) => ({ name: parameter.getAttribute('name'), index }));
    requireCondition(parameters.every(parameter => !parameter.getAttribute('type') || parameter.getAttribute('type') === 'float'), 'Unsupported non-scalar COLLADA accessor parameter');
    requireCondition(parameters.length <= stride && offset + Math.max(0, count - 1) * stride + parameters.length <= values.length, 'COLLADA accessor exceeds array');
    const read = (index, semantic) => {
      requireCondition(Number.isSafeInteger(index) && index >= 0 && index < count, 'COLLADA index outside accessor');
      const names = semantic === 'COLOR' ? ['R', 'G', 'B', 'A'] : ['X', 'Y', 'Z'];
      const selected = names.map(name => slots.find(slot => slot.name === name)?.index);
      const named = selected.slice(0, 3).every(value => value !== undefined);
      const components = named ? selected : (slots.some(slot => slot.name) ? slots.filter(slot => slot.name).map(slot => slot.index) : Array.from({ length: Math.min(stride, names.length) }, (value, position) => position));
      requireCondition(components.length >= 3 && components.slice(0, 3).every(value => value !== undefined), 'COLLADA source lacks three components');
      const output = components.slice(0, names.length).map((component, position) => component === undefined && position === 3 ? 1 : values[offset + index * stride + component]);
      if (semantic === 'COLOR' && output.length === 3) output.push(1);
      requireCondition(output.every(Number.isFinite), 'Invalid COLLADA source sample');
      return output;
    };
    sourceCache.set(reference, read);
    return read;
  };
  const materialColor = material => {
    if (!material) return null;
    const effectReference = child(material, 'instance_effect')?.getAttribute('url');
    requireCondition(effectReference, 'COLLADA material has no effect');
    const profile = child(resolve(effectReference), 'profile_COMMON');
    requireCondition(profile, 'Unsupported COLLADA material profile');
    const technique = child(profile, 'technique');
    const shader = Array.from(technique?.children ?? []).find(element => ['phong', 'lambert', 'blinn', 'constant'].includes(element.localName));
    requireCondition(shader, 'Unsupported COLLADA material shader');
    const diffuse = child(shader, shader.localName === 'constant' ? 'emission' : 'diffuse');
    requireCondition(!child(diffuse, 'texture'), 'COLLADA textured diffuse requires a texture renderer; no geometry substituted');
    const color = rgba(child(diffuse, 'color')?.textContent, [0.7, 0.7, 0.7, 1]);
    const transparent = child(shader, 'transparent');
    const transparency = Number(child(child(shader, 'transparency'), 'float')?.textContent ?? 1);
    requireCondition(Number.isFinite(transparency), 'Invalid COLLADA transparency');
    if (transparent) {
      requireCondition(!child(transparent, 'texture'), 'COLLADA transparency textures are unsupported');
      const channels = rgba(child(transparent, 'color')?.textContent, [1, 1, 1, 1]);
      const opaque = transparent.getAttribute('opaque') ?? 'A_ONE';
      let opacity;
      if (opaque === 'A_ONE') opacity = channels[3] * transparency;
      else if (opaque === 'A_ZERO') opacity = 1 - channels[3] * transparency;
      else if (opaque === 'RGB_ONE') opacity = (channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722) * transparency;
      else if (opaque === 'RGB_ZERO') opacity = 1 - (channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722) * transparency;
      else throw new Error(`Unsupported COLLADA opaque mode: ${opaque}`);
      color[3] *= Math.max(0, Math.min(1, opacity));
    }
    return color;
  };
  const geometryCache = new Map();
  const readGeometry = element => {
    const identifier = element.getAttribute('id');
    if (geometryCache.has(identifier)) return geometryCache.get(identifier);
    const mesh = child(element, 'mesh');
    requireCondition(mesh, 'Only COLLADA mesh geometry is supported');
    const output = [];
    for (const primitive of Array.from(mesh.children)) {
      const kind = primitive.localName;
      if (['source', 'vertices', 'extra'].includes(kind)) continue;
      requireCondition(['triangles', 'polylist', 'polygons', 'trifans', 'tristrips'].includes(kind), `Unsupported COLLADA primitive: ${kind}`);
      const inputs = children(primitive, 'input').map(input => ({
        semantic: input.getAttribute('semantic'), source: input.getAttribute('source'),
        offset: integer(input.getAttribute('offset') ?? 0, 'primitive offset'),
        set: integer(input.getAttribute('set') ?? 0, 'input set')
      }));
      requireCondition(inputs.length > 0, 'COLLADA primitive has no inputs');
      const stride = Math.max(...inputs.map(input => input.offset)) + 1;
      const expanded = [];
      for (const input of inputs) {
        if (input.semantic !== 'VERTEX') {
          expanded.push(input);
          continue;
        }
        const vertices = resolve(input.source);
        requireCondition(vertices.localName === 'vertices', 'VERTEX input must reference vertices');
        for (const nested of children(vertices, 'input')) {
          expanded.push({ semantic: nested.getAttribute('semantic'), source: nested.getAttribute('source'), offset: input.offset, set: integer(nested.getAttribute('set') ?? 0, 'vertex input set') });
        }
      }
      const positionInput = expanded.find(input => input.semantic === 'POSITION');
      requireCondition(positionInput, 'COLLADA primitive lacks POSITION');
      const positionSource = readSource(positionInput.source);
      const colorInput = expanded.find(input => input.semantic === 'COLOR' && input.set === 0);
      const colorSource = colorInput ? readSource(colorInput.source) : null;
      const geometry = makeGeometry();
      const indexLists = children(primitive, 'p').map(element => {
        const indices = numberList(element.textContent);
        requireCondition(indices.every(value => Number.isSafeInteger(value) && value >= 0) && indices.length % stride === 0, 'Invalid COLLADA primitive indices');
        return indices;
      });
      const count = integer(primitive.getAttribute('count'), 'primitive count');
      requireCondition(children(primitive, 'ph').length === 0, 'COLLADA polygon holes are unsupported');
      const emit = (indices, corners) => {
        const positions = corners.map(corner => positionSource(indices[corner * stride + positionInput.offset], 'POSITION'));
        const colors = colorSource ? corners.map(corner => colorSource(indices[corner * stride + colorInput.offset], 'COLOR')) : null;
        appendTriangle(geometry, positions, colors);
      };
      if (kind === 'triangles') {
        const indices = indexLists.flat();
        requireCondition(indices.length === count * 3 * stride, 'COLLADA triangle count mismatch');
        for (let corner = 0; corner < count * 3; corner += 3) emit(indices, [corner, corner + 1, corner + 2]);
      } else if (kind === 'polylist') {
        const sizes = numberList(child(primitive, 'vcount')?.textContent);
        requireCondition(sizes.length === count && sizes.every(size => Number.isSafeInteger(size) && size >= 3), 'COLLADA polylist count mismatch');
        const indices = indexLists.flat();
        requireCondition(sizes.reduce((sum, size) => sum + size, 0) * stride === indices.length, 'COLLADA polylist index length mismatch');
        let start = 0;
        for (const size of sizes) {
          const polygon = Array.from({ length: size }, (value, index) => positionSource(indices[(start + index) * stride + positionInput.offset], 'POSITION'));
          for (const triangle of triangulatePolygon(polygon)) emit(indices, triangle.map(index => start + index));
          start += size;
        }
      } else {
        requireCondition(indexLists.length === count, 'COLLADA polygon/fan/strip count mismatch');
        for (const indices of indexLists) {
          const size = indices.length / stride;
          requireCondition(size >= 3, 'COLLADA primitive has fewer than three vertices');
          if (kind === 'polygons') {
            const polygon = Array.from({ length: size }, (value, index) => positionSource(indices[index * stride + positionInput.offset], 'POSITION'));
            for (const triangle of triangulatePolygon(polygon)) emit(indices, triangle);
          } else {
            for (let index = 1; index < size - 1; index += 1) {
              const triangle = kind === 'trifans' ? [0, index, index + 1] : (index % 2 === 1 ? [index - 1, index, index + 1] : [index, index - 1, index + 1]);
              emit(indices, triangle);
            }
          }
        }
      }
      output.push({ geometry, symbol: primitive.getAttribute('material') });
    }
    geometryCache.set(identifier, output);
    return output;
  };
  const asset = child(document.documentElement, 'asset');
  const meter = Number(child(asset, 'unit')?.getAttribute('meter') ?? 1);
  requireCondition(Number.isFinite(meter) && meter > 0, 'Invalid COLLADA unit');
  const upAxis = child(asset, 'up_axis')?.textContent.trim() ?? 'Y_UP';
  requireCondition(['X_UP', 'Y_UP', 'Z_UP'].includes(upAxis), `Unsupported COLLADA up_axis: ${upAxis}`);
  const upTransform = upAxis === 'Y_UP' ? rotation([1, 0, 0], Math.PI / 2) : upAxis === 'X_UP' ? rotation([0, 1, 0], -Math.PI / 2) : identity();
  const assetTransform = multiply(upTransform, scaling([meter, meter, meter]));
  const batches = [];
  let vertexTotal = 0;
  const instantiate = (instance, transform) => {
    const element = resolve(instance.getAttribute('url'));
    requireCondition(element.localName === 'geometry', 'Expected instance_geometry target');
    const bindings = new Map();
    const common = child(child(instance, 'bind_material'), 'technique_common');
    for (const binding of children(common, 'instance_material')) bindings.set(binding.getAttribute('symbol'), resolve(binding.getAttribute('target')));
    for (const batch of readGeometry(element)) {
      const baked = makeGeometry();
      for (let offset = 0; offset < batch.geometry.positions.length; offset += 9) {
        const vertices = [0, 1, 2].map(index => point(transform, batch.geometry.positions.slice(offset + index * 3, offset + index * 3 + 3)));
        const colors = [0, 1, 2].map(index => batch.geometry.colors.slice(offset / 3 * 4 + index * 4, offset / 3 * 4 + index * 4 + 4));
        appendTriangle(baked, vertices, colors);
      }
      vertexTotal += baked.positions.length / 3;
      requireCondition(vertexTotal <= MAX_VERTICES, 'Instanced COLLADA exceeds vertex limit');
      const boundMaterial = bindings.get(batch.symbol);
      requireCondition(!batch.symbol || boundMaterial, `Unbound COLLADA material symbol: ${batch.symbol}`);
      batches.push({ geometry: baked, color: overrideColor ?? materialColor(boundMaterial) });
    }
  };
  const visit = (node, parent, ancestry = new Set()) => {
    requireCondition(!ancestry.has(node) && ancestry.size < 256, 'Cyclic or excessively deep COLLADA scene');
    const nextAncestry = new Set(ancestry).add(node);
    let local = identity();
    for (const transform of Array.from(node.children)) {
      let matrix = null;
      if (transform.localName === 'matrix') {
        const values = numberList(transform.textContent, 16);
        matrix = Array.from({ length: 16 }, (value, index) => values[(index % 4) * 4 + Math.floor(index / 4)]);
        requireCondition(Math.abs(matrix[3]) < EPSILON && Math.abs(matrix[7]) < EPSILON && Math.abs(matrix[11]) < EPSILON && Math.abs(matrix[15] - 1) < EPSILON, 'Non-affine COLLADA matrix');
      } else if (transform.localName === 'translate') matrix = translation(numberList(transform.textContent, 3));
      else if (transform.localName === 'scale') matrix = scaling(numberList(transform.textContent, 3));
      else if (transform.localName === 'rotate') {
        const values = numberList(transform.textContent, 4);
        matrix = rotation(values.slice(0, 3), values[3] * Math.PI / 180);
      } else if (['lookat', 'skew'].includes(transform.localName)) throw new Error(`Unsupported COLLADA transform: ${transform.localName}`);
      if (matrix) local = multiply(local, matrix);
    }
    const world = multiply(parent, local);
    for (const instance of children(node, 'instance_geometry')) instantiate(instance, world);
    requireCondition(children(node, 'instance_controller').length === 0, 'Skinned COLLADA controllers are unsupported');
    for (const nested of children(node, 'node')) visit(nested, world, nextAncestry);
    for (const instance of children(node, 'instance_node')) {
      const target = resolve(instance.getAttribute('url'));
      requireCondition(target.localName === 'node', 'Invalid COLLADA instance_node');
      visit(target, world, nextAncestry);
    }
  };
  const sceneInstance = child(child(document.documentElement, 'scene'), 'instance_visual_scene');
  if (sceneInstance) {
    const scene = resolve(sceneInstance.getAttribute('url'));
    requireCondition(scene.localName === 'visual_scene', 'Invalid COLLADA visual scene');
    for (const node of children(scene, 'node')) visit(node, assetTransform);
  } else {
    const scenes = descendants(document, 'visual_scene');
    requireCondition(scenes.length <= 1, 'COLLADA has ambiguous unselected visual scenes');
    if (scenes.length === 1) {
      for (const node of children(scenes[0], 'node')) visit(node, assetTransform);
    } else {
      const geometries = descendants(document, 'geometry');
      requireCondition(geometries.length > 0, 'COLLADA has no geometry');
      for (const geometry of geometries) {
        const instance = document.createElement('instance_geometry');
        instance.setAttribute('url', `#${geometry.getAttribute('id')}`);
        instantiate(instance, assetTransform);
      }
    }
  }
  requireCondition(batches.some(batch => batch.geometry.positions.length > 0), 'COLLADA contains no renderable visual triangles');
  return batches;
}

function shaderProgram(gl) {
  const vertexSource = `
    attribute vec3 aPosition;
    attribute vec3 aNormal;
    attribute vec4 aColor;
    uniform mat4 uModel;
    uniform mat4 uViewProjection;
    uniform mat3 uNormal;
    varying vec3 vNormal;
    varying vec4 vColor;
    void main() {
      gl_Position = uViewProjection * uModel * vec4(aPosition, 1.0);
      vNormal = normalize(uNormal * aNormal);
      vColor = aColor;
    }
  `;
  const fragmentSource = `
    precision mediump float;
    uniform vec4 uColor;
    varying vec3 vNormal;
    varying vec4 vColor;
    void main() {
      vec3 normal = normalize(vNormal);
      if (!gl_FrontFacing) normal = -normal;
      float lighting = 0.38 + 0.62 * max(dot(normal, normalize(vec3(0.5, -0.6, 1.0))), 0.0);
      vec4 color = uColor * vColor;
      gl_FragColor = vec4(color.rgb * lighting, color.a);
    }
  `;
  const shaders = [];
  let program = null;
  try {
    for (const [type, source] of [[gl.VERTEX_SHADER, vertexSource], [gl.FRAGMENT_SHADER, fragmentSource]]) {
      const shader = gl.createShader(type);
      requireCondition(shader, 'Cannot allocate WebGL shader');
      shaders.push(shader);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      requireCondition(gl.getShaderParameter(shader, gl.COMPILE_STATUS), `Shader compile failed: ${gl.getShaderInfoLog(shader)}`);
    }
    program = gl.createProgram();
    requireCondition(program, 'Cannot allocate WebGL program');
    for (const shader of shaders) gl.attachShader(program, shader);
    gl.linkProgram(program);
    requireCondition(gl.getProgramParameter(program, gl.LINK_STATUS), `Shader link failed: ${gl.getProgramInfoLog(program)}`);
    return program;
  } catch (error) {
    if (program) gl.deleteProgram(program);
    throw error;
  } finally {
    for (const shader of shaders) gl.deleteShader(shader);
  }
}

function lookAt(eye, target) {
  const backward = normalized(subtract(eye, target));
  const right = normalized(cross([0, 0, 1], backward));
  const up = cross(backward, right);
  return [right[0], up[0], backward[0], 0, right[1], up[1], backward[1], 0, right[2], up[2], backward[2], 0, -dot(right, eye), -dot(up, eye), -dot(backward, eye), 1];
}

function orthographic(horizontal, vertical, depth) {
  return [1 / horizontal, 0, 0, 0, 0, 1 / vertical, 0, 0, 0, 0, -1 / depth, 0, 0, 0, 0, 1];
}

export class RobotRenderer extends Reporter {
  constructor(canvas, options = {}) {
    super(canvas, options);
    this.gl = canvas.getContext('webgl', { alpha: false, antialias: true });
    requireCondition(this.gl, 'WebGL is unavailable; no substitute robot view is provided');
    this.abortController = new AbortController();
    this.links = new Map();
    this.joints = new Map();
    this.jointPositions = new Map();
    this.batches = [];
    this.meshCache = new Map();
    this.pose = null;
    this.viewCenter = null;
    this.explicitView = false;
    this.viewSpan = options.span ?? 0.9;
    requireCondition(Number.isFinite(this.viewSpan) && this.viewSpan > 0, 'Invalid robot world-view span');
    this.program = shaderProgram(this.gl);
    this.locations = {
      position: this.gl.getAttribLocation(this.program, 'aPosition'),
      normal: this.gl.getAttribLocation(this.program, 'aNormal'),
      color: this.gl.getAttribLocation(this.program, 'aColor'),
      model: this.gl.getUniformLocation(this.program, 'uModel'),
      viewProjection: this.gl.getUniformLocation(this.program, 'uViewProjection'),
      normalMatrix: this.gl.getUniformLocation(this.program, 'uNormal'),
      material: this.gl.getUniformLocation(this.program, 'uColor')
    };
    // Metric reference only: this grid is not an environment map or robot mesh.
    const grid = { positions: [], normals: [], colors: [] };
    for (let n = -100; n <= 100; n++) {
      const position = n * 0.1;
      for (const point of [[position, -10, -0.01], [position, 10, -0.01], [-10, position, -0.01], [10, position, -0.01]]) {
        grid.positions.push(...point); grid.normals.push(0, 0, 1);
        grid.colors.push(0.25, 0.38, 0.45, 1);
      }
    }
    this.grid = this.upload(grid, { color: [1, 1, 1, 1], primitive: this.gl.LINES });
    this.contextLost = false;
    this.onContextLost = event => {
      event.preventDefault();
      this.contextLost = true;
      this.fail(new Error('WebGL context lost; reload the page to reload the actual model'));
    };
    this.onContextRestored = () => {
      this.status('WebGL context restored; reload required to recreate mesh buffers', 'error');
    };
    canvas.addEventListener('webglcontextlost', this.onContextLost);
    canvas.addEventListener('webglcontextrestored', this.onContextRestored);
    this.observeResize();
    this.resize();
    this.status('Loading course URDF visual assets', 'loading');
    const urdfUrl = new URL(options.urdfUrl ?? './assets/fastbot.urdf', document.baseURI);
    this.ready = this.load(urdfUrl).then(() => {
      if (this.disposed) return this;
      this.draw();
      this.status(this.pose ? 'Course meshes loaded · measured map pose' : 'Course meshes loaded · waiting for measured map pose', this.pose ? 'ready' : 'unavailable');
      return this;
    }).catch(error => {
      this.releaseBuffers();
      if (!this.disposed) throw this.fail(error);
      throw error;
    });
    this.ready.catch(() => {});
  }

  async fetchResource(url, text = false) {
    requireCondition(['http:', 'https:'].includes(url.protocol) && url.origin === new URL(document.baseURI).origin, 'Robot resources must be served from the dashboard origin');
    const response = await fetch(url, { signal: this.abortController.signal, credentials: 'same-origin' });
    requireCondition(response.ok, `Asset HTTP ${response.status}: ${url.pathname}`);
    const declaredSize = Number(response.headers.get('content-length') ?? 0);
    requireCondition(!Number.isFinite(declaredSize) || declaredSize <= MAX_RESOURCE_BYTES, `Asset exceeds size limit: ${url.pathname}`);
    const buffer = await response.arrayBuffer();
    requireCondition(buffer.byteLength <= MAX_RESOURCE_BYTES, `Asset exceeds size limit: ${url.pathname}`);
    this.check();
    return text ? new TextDecoder().decode(buffer) : buffer;
  }

  mesh(url, overrideColor = null) {
    const cacheKey = url.href + JSON.stringify(overrideColor);
    if (!this.meshCache.has(cacheKey)) {
      const promise = this.fetchResource(url).then(buffer => {
        const extension = url.pathname.split('.').pop().toLowerCase();
        if (extension === 'stl') return parseStl(buffer);
        if (extension === 'dae') return parseCollada(buffer, overrideColor);
        throw new Error(`Unsupported visual mesh extension: ${url.pathname}`);
      });
      this.meshCache.set(cacheKey, promise);
    }
    return this.meshCache.get(cacheKey);
  }

  async load(url) {
    const document = parseXml(await this.fetchResource(url, true), 'URDF');
    const robot = document.documentElement;
    requireCondition(robot.localName === 'robot', 'Expected URDF robot element');
    const materials = new Map();
    for (const material of children(robot, 'material')) {
      requireCondition(!child(material, 'texture'), 'URDF material textures are unsupported');
      const color = child(material, 'color');
      if (color) materials.set(material.getAttribute('name'), rgba(color.getAttribute('rgba')));
    }
    for (const element of children(robot, 'link')) {
      const name = element.getAttribute('name');
      requireCondition(name && !this.links.has(name), 'Missing or duplicate URDF link name');
      this.links.set(name, { element, parentJoint: null });
    }
    requireCondition(this.links.size > 0, 'URDF has no links');
    for (const element of children(robot, 'joint')) {
      const name = element.getAttribute('name');
      const type = element.getAttribute('type');
      requireCondition(name && !this.joints.has(name), 'Missing or duplicate URDF joint name');
      requireCondition(['fixed', 'continuous', 'revolute', 'prismatic'].includes(type), `Unsupported URDF joint type: ${type}`);
      const parent = child(element, 'parent')?.getAttribute('link');
      const childName = child(element, 'child')?.getAttribute('link');
      requireCondition(this.links.has(parent) && this.links.has(childName), `Unknown link in joint ${name}`);
      requireCondition(!this.links.get(childName).parentJoint, `Multiple parents for link ${childName}`);
      const axis = type === 'fixed' ? [1, 0, 0] : normalized(numberList(child(element, 'axis')?.getAttribute('xyz') ?? '1 0 0', 3));
      const joint = { name, type, parent, child: childName, origin: originMatrix(child(element, 'origin')), axis };
      this.links.get(childName).parentJoint = joint;
      this.joints.set(name, joint);
    }
    const roots = [...this.links].filter(([, link]) => !link.parentJoint).map(([name]) => name);
    requireCondition(roots.length === 1, 'URDF must have one connected root link');
    this.rootLink = roots[0];
    this.linkMatrices();
    let vertexTotal = 0;
    for (const [linkName, link] of this.links) {
      for (const visual of children(link.element, 'visual')) {
        const geometry = child(visual, 'geometry');
        const mesh = child(geometry, 'mesh');
        requireCondition(mesh && geometry.children.length === 1, `Unsupported non-mesh visual on ${linkName}; no substitute geometry used`);
        const filename = mesh.getAttribute('filename');
        requireCondition(filename && !/^(package|file):/i.test(filename), `Visual mesh must have a served relative URL: ${filename}`);
        const meshUrl = new URL(filename, url);
        const scale = numberList(mesh.getAttribute('scale') ?? '1 1 1', 3);
        requireCondition(scale.every(value => Math.abs(value) > EPSILON), 'Zero URDF mesh scale');
        const visualTransform = multiply(originMatrix(child(visual, 'origin')), scaling(scale));
        const material = child(visual, 'material');
        requireCondition(!child(material, 'texture'), `Unsupported URDF visual texture on ${linkName}`);
        const materialName = material?.getAttribute('name');
        const explicitColor = rgba(child(material, 'color')?.getAttribute('rgba'), materials.get(materialName) ?? null);
        requireCondition(!material || explicitColor, `Unresolved URDF material: ${materialName}`);
        const meshBatches = await this.mesh(meshUrl, explicitColor);
        this.check();
        for (const batch of meshBatches) {
          if (batch.geometry.positions.length === 0) continue;
          vertexTotal += batch.geometry.positions.length / 3;
          requireCondition(vertexTotal <= MAX_VERTICES, 'Robot visuals exceed total vertex limit');
          this.batches.push(this.upload(batch.geometry, { linkName, visualTransform, color: explicitColor ?? batch.color ?? [0.7, 0.7, 0.7, 1] }));
        }
      }
    }
    requireCondition(this.batches.length > 0, 'URDF has no renderable mesh visuals');
    this.loaded = true;
  }

  upload(geometry, properties) {
    const gl = this.gl;
    const buffers = [];
    try {
      for (const values of [geometry.positions, geometry.normals, geometry.colors]) {
        const buffer = gl.createBuffer();
        requireCondition(buffer, 'Cannot allocate WebGL mesh buffer');
        buffers.push(buffer);
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(values), gl.STATIC_DRAW);
        requireCondition(gl.getError() === gl.NO_ERROR, 'WebGL mesh upload failed');
      }
      return { ...properties, buffers, count: geometry.positions.length / 3 };
    } catch (error) {
      for (const buffer of buffers) gl.deleteBuffer(buffer);
      throw error;
    }
  }

  linkMatrices() {
    const matrices = new Map();
    const resolve = (name, ancestry = new Set()) => {
      if (matrices.has(name)) return matrices.get(name);
      requireCondition(!ancestry.has(name) && ancestry.size < 256, 'Cyclic or excessively deep URDF hierarchy');
      const link = this.links.get(name);
      const joint = link.parentJoint;
      let matrix = identity();
      if (joint) {
        const position = this.jointPositions.get(joint.name) ?? 0;
        const motion = joint.type === 'fixed' ? identity() : joint.type === 'prismatic' ? translation(joint.axis.map(value => value * position)) : rotation(joint.axis, position);
        matrix = multiply(resolve(joint.parent, new Set(ancestry).add(name)), multiply(joint.origin, motion));
      }
      matrices.set(name, matrix);
      return matrix;
    };
    for (const name of this.links.keys()) resolve(name);
    return matrices;
  }

  update(message) {
    return this.updatePose(message);
  }

  updatePose(message) {
    this.check();
    try {
      this.pose = message === null ? null : checkedPose(message, this.mapFrame);
      if (this.pose && !this.explicitView) this.viewCenter = [this.pose[12], this.pose[13], this.pose[14] + 0.1];
      this.draw();
      if (this.loaded) this.status(this.pose ? 'Course meshes · measured map pose' : 'Map pose unavailable; robot hidden', this.pose ? 'ready' : 'unavailable');
    } catch (error) {
      this.pose = null;
      this.draw();
      throw this.fail(error);
    }
  }

  updateJointState(message) {
    this.check();
    try {
      requireCondition(Array.isArray(message?.name) && Array.isArray(message.position) && message.name.length === message.position.length, 'JointState requires matching name and position arrays');
      const updates = new Map();
      for (let index = 0; index < message.name.length; index += 1) {
        const value = message.position[index];
        requireCondition(typeof value === 'number' && Number.isFinite(value), 'Nonfinite joint position');
        const joint = this.joints.get(message.name[index]);
        if (joint && joint.type !== 'fixed') updates.set(joint.name, value);
      }
      for (const [name, value] of updates) this.jointPositions.set(name, value);
      this.draw();
    } catch (error) {
      throw this.fail(error);
    }
  }

  setView({ center, span }) {
    this.check();
    try {
      requireCondition(Array.isArray(center) && center.length === 3 && center.every(Number.isFinite), 'View center must be three finite world coordinates');
      requireCondition(Number.isFinite(span) && span > 0, 'View span must be positive meters');
      this.viewCenter = [...center];
      this.viewSpan = span;
      this.explicitView = true;
      this.draw();
    } catch (error) {
      throw this.fail(error);
    }
  }

  setFollowView(span = 0.9) {
    this.check();
    requireCondition(Number.isFinite(span) && span > 0, 'Follow span must be positive meters');
    this.explicitView = false;
    this.viewSpan = span;
    if (this.pose) this.viewCenter = [this.pose[12], this.pose[13], this.pose[14] + 0.1];
    this.draw();
  }

  resize() {
    this.resizeSurface();
    this.draw();
  }

  draw() {
    if (this.disposed || this.contextLost) return;
    const gl = this.gl;
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0.031, 0.055, 0.094, 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!this.loaded || !this.pose || !this.viewCenter) return;
    const center = this.viewCenter;
    const span = this.viewSpan;
    const eye = [center[0] + span * 0.7, center[1] - span * 0.9, center[2] + span * 0.8];
    const aspect = this.canvas.width / Math.max(1, this.canvas.height);
    const vertical = span / 2;
    const projection = orthographic(vertical * aspect, vertical, span * 20 + 100);
    const viewProjection = multiply(projection, lookAt(eye, center));
    gl.useProgram(this.program);
    gl.enable(gl.DEPTH_TEST);
    gl.disable(gl.CULL_FACE);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.uniformMatrix4fv(this.locations.viewProjection, false, new Float32Array(viewProjection));
    const links = this.linkMatrices();
    const draws = this.batches.map(batch => {
      const model = multiply(this.pose, multiply(links.get(batch.linkName), batch.visualTransform));
      return { batch, model, distance: Math.hypot(...subtract(point(model, [0, 0, 0]), eye)) };
    });
    if (this.grid) draws.unshift({ batch: this.grid, model: identity(), distance: 0 });
    draws.sort((left, right) => {
      const leftTransparent = left.batch.color[3] < 1;
      const rightTransparent = right.batch.color[3] < 1;
      return leftTransparent !== rightTransparent ? Number(leftTransparent) - Number(rightTransparent) : leftTransparent ? right.distance - left.distance : 0;
    });
    for (const { batch, model } of draws) {
      gl.depthMask(batch.color[3] >= 1);
      for (const [index, location, size] of [[0, this.locations.position, 3], [1, this.locations.normal, 3], [2, this.locations.color, 4]]) {
        gl.bindBuffer(gl.ARRAY_BUFFER, batch.buffers[index]);
        gl.enableVertexAttribArray(location);
        gl.vertexAttribPointer(location, size, gl.FLOAT, false, 0, 0);
      }
      gl.uniformMatrix4fv(this.locations.model, false, new Float32Array(model));
      gl.uniformMatrix3fv(this.locations.normalMatrix, false, new Float32Array(normalMatrix(model)));
      gl.uniform4fv(this.locations.material, new Float32Array(batch.color));
      gl.drawArrays(batch.primitive ?? gl.TRIANGLES, 0, batch.count);
    }
    gl.depthMask(true);
  }

  clear() {
    this.check();
    this.pose = null;
    this.jointPositions.clear();
    if (!this.explicitView) this.viewCenter = null;
    this.draw();
    this.status(this.loaded ? 'Course meshes loaded · waiting for measured map pose' : 'Waiting for course visual assets', 'unavailable');
  }

  releaseBuffers() {
    for (const batch of this.batches) {
      for (const buffer of batch.buffers) this.gl.deleteBuffer(buffer);
    }
    this.batches = [];
    this.loaded = false;
  }

  dispose() {
    if (this.disposed) return;
    this.abortController.abort();
    this.canvas.removeEventListener('webglcontextlost', this.onContextLost);
    this.canvas.removeEventListener('webglcontextrestored', this.onContextRestored);
    this.releaseBuffers();
    if (this.grid) { for (const buffer of this.grid.buffers) this.gl.deleteBuffer(buffer); this.grid = null; }
    this.gl.deleteProgram(this.program);
    this.meshCache.clear();
    this.pose = null;
    this.gl.clear(this.gl.COLOR_BUFFER_BIT | this.gl.DEPTH_BUFFER_BIT);
    super.dispose();
  }
}
