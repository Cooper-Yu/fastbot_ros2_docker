export function planarPose(pose) {
  const position = pose?.position, rotation = pose?.orientation;
  if (!position || !rotation || ![position.x, position.y, position.z, rotation.x, rotation.y, rotation.z, rotation.w].every(Number.isFinite)) throw new Error('无效位姿');
  const norm = rotation.x ** 2 + rotation.y ** 2 + rotation.z ** 2 + rotation.w ** 2;
  if (Math.abs(norm - 1) > 0.01) throw new Error('无效四元数');
  const scale = Math.sqrt(norm), rx = rotation.x / scale, ry = rotation.y / scale, rz = rotation.z / scale, rw = rotation.w / scale;
  return {x: position.x, y: position.y, yaw: Math.atan2(2 * (rw * rz + rx * ry), 1 - 2 * (ry * ry + rz * rz))};
}
export class Renderers {
  constructor(map, robot, camera) {
    this.canvas = map; this.context = map.getContext('2d'); this.robotCanvas = robot;
    this.cameraCanvas = camera; this.cameraContext = camera.getContext('2d');
    this.pose = null; this.grid = null; this.projection = null;
    this.gl = robot.getContext('webgl', {alpha: true, premultipliedAlpha: false});
    if (this.gl) {
      const gl = this.gl;
      const shader = (type, source) => { const item = gl.createShader(type); gl.shaderSource(item, source); gl.compileShader(item); if (!gl.getShaderParameter(item, gl.COMPILE_STATUS)) throw new Error('WebGL shader unavailable'); return item; };
      try {
        this.program = gl.createProgram();
        gl.attachShader(this.program, shader(gl.VERTEX_SHADER, 'attribute vec3 position;attribute vec3 color;varying vec3 shade;void main(){gl_Position=vec4(position,1.0);shade=color;}'));
        gl.attachShader(this.program, shader(gl.FRAGMENT_SHADER, 'precision mediump float;varying vec3 shade;void main(){gl_FragColor=vec4(shade,1.0);}'));
        gl.linkProgram(this.program); if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) throw new Error('WebGL link unavailable');
        this.buffer = gl.createBuffer();
      } catch { this.gl = null; }
    }
    robot.addEventListener('webglcontextlost', event => { event.preventDefault(); this.gl = null; robot.style.visibility = 'hidden'; });
    this.resizeObserver = new ResizeObserver(() => {
      const box = map.parentElement.getBoundingClientRect(), ratio = Math.min(window.devicePixelRatio || 1, 2);
      if (box.width < 1 || box.height < 1) return;
      map.width = robot.width = Math.round(box.width * ratio); map.height = robot.height = Math.round(box.height * ratio);
      if (this.grid) this.map(this.grid); this.robot(this.pose);
    });
    this.resizeObserver.observe(map.parentElement);
  }
  clearCamera() { this.cameraContext.clearRect(0, 0, this.cameraCanvas.width, this.cameraCanvas.height); }
  clear() {
    this.grid = this.pose = this.projection = null;
    this.context.clearRect(0, 0, this.canvas.width, this.canvas.height); this.clearCamera(); this.robot(null);
  }
  map(message) {
    const info = message.info, data = message.data;
    if (message.header?.frame_id !== 'map' || !info || !Number.isInteger(info.width) || !Number.isInteger(info.height) || info.width <= 0 || info.height <= 0 || info.width > 4096 || info.height > 4096 || info.width * info.height > 4194304 || !Number.isFinite(info.resolution) || info.resolution <= 0 || !Array.isArray(data) || data.length !== info.width * info.height) throw new Error('无效或过大的map OccupancyGrid');
    const origin = planarPose(info.origin), cosine = Math.cos(origin.yaw), sine = Math.sin(origin.yaw);
    if (Math.abs(info.origin.orientation.x) > 0.001 || Math.abs(info.origin.orientation.y) > 0.001) throw new Error('不支持倾斜地图');
    const width = info.width * info.resolution, height = info.height * info.resolution;
    const corners = [[0, 0], [width, 0], [0, height], [width, height]].map(([x, y]) => [origin.x + cosine * x - sine * y, origin.y + sine * x + cosine * y]);
    const xs = corners.map(point => point[0]), ys = corners.map(point => point[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const scale = Math.min((this.canvas.width - 32) / (maxX - minX), (this.canvas.height - 32) / (maxY - minY));
    if (![minX, maxX, minY, maxY, scale].every(Number.isFinite) || scale <= 0) throw new Error('地图坐标范围无效');
    const centerX = minX + (maxX - minX) / 2, centerY = minY + (maxY - minY) / 2;
    const raster = document.createElement('canvas'); raster.width = info.width; raster.height = info.height;
    const context = raster.getContext('2d'), image = context.createImageData(info.width, info.height);
    for (let index = 0; index < data.length; index++) {
      const value = data[index];
      if (!Number.isInteger(value) || value < -1 || value > 100) throw new Error('非法占据概率');
      const gray = value < 0 ? 105 : Math.round(245 * (1 - value / 100));
      image.data.set([gray, gray, gray, 255], index * 4);
    }
    context.putImageData(image, 0, 0);
    this.projection = {scale, centerX, centerY}; this.grid = message;
    const target = this.context; target.setTransform(1, 0, 0, 1, 0, 0); target.clearRect(0, 0, this.canvas.width, this.canvas.height);
    target.save(); target.translate(this.canvas.width / 2, this.canvas.height / 2); target.scale(scale, -scale);
    target.translate(origin.x - centerX, origin.y - centerY); target.rotate(origin.yaw); target.scale(info.resolution, info.resolution);
    target.imageSmoothingEnabled = false; target.drawImage(raster, 0, 0); target.restore();
  }
  robot(pose) {
    const gl = this.gl; this.robotCanvas.style.visibility = pose && this.projection && gl ? 'visible' : 'hidden';
    if (!gl) return;
    gl.viewport(0, 0, this.robotCanvas.width, this.robotCanvas.height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!pose || !this.projection) return;
    const {scale, centerX, centerY} = this.projection, cosine = Math.cos(pose.yaw), sine = Math.sin(pose.yaw);
    const corners = [[-.18, -.13, 0], [.18, -.13, 0], [.18, .13, 0], [-.18, .13, 0], [-.18, -.13, .25], [.18, -.13, .25], [.18, .13, .25], [-.18, .13, .25]];
    const vertices = corners.map(([x, y, z]) => {
      const worldX = pose.x + cosine * x - sine * y, worldY = pose.y + sine * x + cosine * y;
      return [2 * scale * (worldX - centerX + z * .3) / this.canvas.width, 2 * scale * (worldY - centerY + z * .45) / this.canvas.height, -z * 2];
    });
    const faces = [[0, 1, 2, 3, .2, .4, .5], [0, 1, 5, 4, .1, .55, .7], [1, 2, 6, 5, 1, .6, .1], [2, 3, 7, 6, .15, .45, .6], [3, 0, 4, 7, .1, .35, .45], [4, 5, 6, 7, .2, .8, .9]], packed = [];
    for (const face of faces) for (const index of [0, 1, 2, 0, 2, 3]) packed.push(...vertices[face[index]], ...face.slice(4));
    gl.useProgram(this.program); gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL); gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(packed), gl.DYNAMIC_DRAW);
    for (const [name, offset] of [['position', 0], ['color', 12]]) { const location = gl.getAttribLocation(this.program, name); gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 24, offset); }
    gl.drawArrays(gl.TRIANGLES, 0, packed.length / 6);
  }
  camera(message) {
    const {width, height, step, encoding, data} = message;
    const channels = encoding === 'mono8' ? 1 : ['rgb8', 'bgr8'].includes(encoding) ? 3 : 0;
    if (!channels) throw new Error(`不支持相机编码：${String(encoding).slice(0, 32)}`);
    if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0 || width > 1280 || height > 720 || !Number.isInteger(step) || step < width * channels || step * height > 4194304) throw new Error('相机尺寸或step超限');
    let bytes;
    if (typeof data === 'string') {
      if (data.length > Math.ceil(4194304 / 3) * 4) throw new Error('相机载荷超限');
      const binary = atob(data); bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
    } else if (Array.isArray(data) && data.length <= 4194304 && data.every(value => Number.isInteger(value) && value >= 0 && value <= 255)) bytes = Uint8Array.from(data);
    else throw new Error('无效相机载荷');
    if (bytes.length !== step * height) throw new Error('相机载荷与step不一致');
    const image = this.cameraContext.createImageData(width, height);
    for (let row = 0; row < height; row++) for (let column = 0; column < width; column++) {
      const source = row * step + column * channels, target = (row * width + column) * 4;
      image.data[target] = bytes[source + (encoding === 'bgr8' ? 2 : 0)];
      image.data[target + 1] = bytes[source + (channels === 1 ? 0 : 1)];
      image.data[target + 2] = bytes[source + (encoding === 'rgb8' ? 2 : 0)]; image.data[target + 3] = 255;
    }
    this.cameraCanvas.width = width; this.cameraCanvas.height = height; this.cameraContext.putImageData(image, 0, 0);
  }
}
