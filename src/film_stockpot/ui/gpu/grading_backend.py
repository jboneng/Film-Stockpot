"""Optional OpenGL GPU backend for live wheel grading."""

from __future__ import annotations

import colorsys
from typing import TYPE_CHECKING

import numpy as np
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImage, QOffscreenSurface, QOpenGLContext, QSurfaceFormat, QVector3D
from PyQt6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)

from film_stockpot.image.grading import (
    _COLOR_GAIN_STRENGTH,
    _COLOR_OFFSET_STRENGTH,
    _LUM_STRENGTH,
)
from film_stockpot.ui.preview_settings import gpu_acceleration_enabled

if TYPE_CHECKING:
    from film_stockpot.image.grading import GradingContext

_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 position;
layout(location = 1) in vec2 texcoord;
out vec2 v_texcoord;
void main() {
    v_texcoord = texcoord;
    gl_Position = vec4(position, 0.0, 1.0);
}
"""

_FRAGMENT_SHADER = f"""
#version 330 core
in vec2 v_texcoord;
out vec4 fragColor;
uniform sampler2D u_image;
uniform vec3 u_shadowTint;
uniform vec3 u_midTint;
uniform vec3 u_hiTint;
uniform float u_shadowSat;
uniform float u_midSat;
uniform float u_hiSat;
uniform float u_shadowLum;
uniform float u_midLum;
uniform float u_hiLum;
uniform float u_blending;
uniform float u_balance;

const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);
const float OFFSET_K = {_COLOR_OFFSET_STRENGTH};
const float GAIN_K = {_COLOR_GAIN_STRENGTH};
const float LUM_K = {_LUM_STRENGTH};

// Accumulate one zone's affine contribution, localized by its weight, matching
// ``apply_wheel_grading`` on the CPU exactly.
void accumulateZone(
    vec3 base, vec3 tint, float sat, float lum, float weight,
    inout vec3 gainAccum, inout vec3 offsetAccum
) {{
    if (sat > 0.0) {{
        vec3 offset = (tint - vec3(0.5)) * 2.0 * sat * OFFSET_K;
        vec3 gainMinusOne = (tint - vec3(1.0)) * sat * GAIN_K;
        gainAccum += weight * gainMinusOne;
        offsetAccum += weight * offset;
    }}
    if (lum != 0.0) {{
        offsetAccum += vec3(weight * lum * LUM_K);
    }}
}}

void main() {{
    vec3 base = texture(u_image, v_texcoord).rgb;
    float luma = dot(base, LUMA);
    float balanceShift = u_balance * 0.30;
    float lumaEff = clamp(luma + balanceShift, 0.0, 1.0);
    float rawShadow = clamp(1.0 - lumaEff * 2.0, 0.0, 1.0);
    float rawHi = clamp(lumaEff * 2.0 - 1.0, 0.0, 1.0);
    float rawMid = clamp(1.0 - rawShadow - rawHi, 0.0, 1.0);
    float power = 2.0 - u_blending * 1.5;
    float shadowW = pow(rawShadow, power);
    float hiW = pow(rawHi, power);
    float midW = pow(rawMid, power);
    float total = max(shadowW + midW + hiW, 1e-6);
    shadowW /= total;
    midW /= total;
    hiW /= total;

    vec3 gainAccum = vec3(0.0);
    vec3 offsetAccum = vec3(0.0);
    accumulateZone(base, u_shadowTint, u_shadowSat, u_shadowLum, shadowW, gainAccum, offsetAccum);
    accumulateZone(base, u_midTint, u_midSat, u_midLum, midW, gainAccum, offsetAccum);
    accumulateZone(base, u_hiTint, u_hiSat, u_hiLum, hiW, gainAccum, offsetAccum);

    vec3 color = base * (vec3(1.0) + gainAccum) + offsetAccum;
    fragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}}
"""


class GpuGradingBackend:
    """Render wheel grading through an OpenGL fragment shader."""

    def __init__(self) -> None:
        self._available: bool | None = None
        self._surface: QOffscreenSurface | None = None
        self._context: QOpenGLContext | None = None
        self._program: QOpenGLShaderProgram | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._vbo: QOpenGLBuffer | None = None
        self._fbo: QOpenGLFramebufferObject | None = None
        self._texture: QOpenGLTexture | None = None
        self._size: tuple[int, int] = (0, 0)

    @property
    def enabled(self) -> bool:
        return gpu_acceleration_enabled() and self.is_available()

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            self._ensure_context()
            self._available = self._context is not None and self._context.isValid()
        except Exception:  # noqa: BLE001
            self._available = False
        return bool(self._available)

    def apply_grading(
        self,
        rgb: np.ndarray,
        grading: dict | None,
        *,
        grading_context: GradingContext | None = None,
    ) -> np.ndarray | None:
        del grading_context
        if not self.enabled:
            return None
        try:
            return self._render(rgb, grading or {})
        except Exception:  # noqa: BLE001
            self._available = False
            return None

    def _ensure_context(self) -> None:
        if self._context is not None and self._context.isValid():
            return
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        self._surface = QOffscreenSurface()
        self._surface.setFormat(fmt)
        self._surface.create()
        self._context = QOpenGLContext()
        self._context.setFormat(fmt)
        if not self._context.create() or not self._context.makeCurrent(self._surface):
            self._context = None
            return
        if self._program is None:
            self._init_gl()

    def _init_gl(self) -> None:
        program = QOpenGLShaderProgram()
        if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, _VERTEX_SHADER):
            raise RuntimeError("GPU grading vertex shader failed")
        if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, _FRAGMENT_SHADER):
            raise RuntimeError("GPU grading fragment shader failed")
        if not program.link():
            raise RuntimeError("GPU grading shader link failed")
        self._program = program

        vertices = np.array(
            [
                -1.0,
                -1.0,
                0.0,
                1.0,
                1.0,
                -1.0,
                1.0,
                1.0,
                -1.0,
                1.0,
                0.0,
                0.0,
                1.0,
                1.0,
                1.0,
                0.0,
            ],
            dtype=np.float32,
        )
        self._vao = QOpenGLVertexArrayObject()
        self._vao.create()
        self._vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._vbo.create()
        self._vao.bind()
        self._vbo.bind()
        self._vbo.allocate(vertices.tobytes(), vertices.nbytes)
        program.bind()
        program.enableAttributeArray(0)
        program.setAttributeBuffer(0, program.defaultAttributeType(), 0, 2, 16)
        program.enableAttributeArray(1)
        program.setAttributeBuffer(1, program.defaultAttributeType(), 8, 2, 16)
        program.release()
        self._vao.release()
        self._vbo.release()

    def _render(self, rgb: np.ndarray, grading: dict) -> np.ndarray | None:
        self._ensure_context()
        if self._context is None or self._program is None:
            return None
        self._context.makeCurrent(self._surface)

        height, width = rgb.shape[:2]
        if self._fbo is None or self._size != (width, height):
            if self._texture is not None:
                self._texture.destroy()
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
            self._fbo = QOpenGLFramebufferObject(QSize(width, height), fmt)
            self._size = (width, height)

        clipped = np.clip(rgb, 0.0, 1.0)
        rgba = np.empty((height, width, 4), dtype=np.uint8)
        rgba[:, :, :3] = (clipped * 255.0 + 0.5).astype(np.uint8)
        rgba[:, :, 3] = 255

        if self._texture is None:
            self._texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
            self._texture.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
            self._texture.setSize(width, height)
            self._texture.allocateStorage()
        self._texture.bind(0)
        self._texture.setData(
            QOpenGLTexture.PixelFormat.RGBA,
            QOpenGLTexture.PixelType.UInt8,
            rgba.tobytes(),
        )

        self._fbo.bind()
        self._program.bind()
        self._program.setUniformValue("u_image", 0)
        self._set_zone_uniforms(grading)
        self._vao.bind()
        self._context.functions().glDrawArrays(0x0005, 0, 4)
        self._vao.release()
        self._program.release()
        self._texture.release()
        self._fbo.release()

        out = self._fbo.toImage().convertToFormat(QImage.Format.Format_RGB888)
        self._context.doneCurrent()
        ptr = out.bits()
        ptr.setsize(out.sizeInBytes())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((height, width, 3))
        return np.ascontiguousarray(arr.astype(np.float32) / 255.0)

    def _set_zone_uniforms(self, grading: dict) -> None:
        def zone(name: str) -> tuple[tuple[float, float, float], float, float]:
            data = grading.get(name, {}) or {}
            hue = float(data.get("hue", 0.0)) % 360.0
            sat = float(data.get("sat", 0.0))
            lum = float(data.get("lum", 0)) / 100.0
            red, green, blue = colorsys.hsv_to_rgb(hue / 360.0, 1.0, 1.0)
            return (red, green, blue), sat, lum

        shadow, shadow_sat, shadow_lum = zone("shadows")
        mid, mid_sat, mid_lum = zone("midtones")
        hi, hi_sat, hi_lum = zone("highlights")
        blending = float(grading.get("blending", 50)) / 100.0
        balance = float(grading.get("balance", 0)) / 100.0

        program = self._program
        program.setUniformValue("u_shadowTint", QVector3D(*shadow))
        program.setUniformValue("u_midTint", QVector3D(*mid))
        program.setUniformValue("u_hiTint", QVector3D(*hi))
        program.setUniformValue("u_shadowSat", shadow_sat)
        program.setUniformValue("u_midSat", mid_sat)
        program.setUniformValue("u_hiSat", hi_sat)
        program.setUniformValue("u_shadowLum", shadow_lum)
        program.setUniformValue("u_midLum", mid_lum)
        program.setUniformValue("u_hiLum", hi_lum)
        program.setUniformValue("u_blending", blending)
        program.setUniformValue("u_balance", balance)
