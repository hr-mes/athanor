"""Prints the OpenGL renderer and version the guest's Mesa gives on its render node.

Run inside the guest by start.sh (`ssh ... python3 - < gl_renderer.py`). glxinfo needs an X
display and the greeter's compositor runs without Xwayland, so this asks through a
surfaceless EGL context instead: the same driver the compositor loads, no display needed.
"virgl" means the guest draws on the host GPU; "llvmpipe" means software rendering.
"""

import ctypes

EGL_PLATFORM_SURFACELESS_MESA = 0x31DD
EGL_OPENGL_API = 0x30A2
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02

egl = ctypes.CDLL("libEGL.so.1")
gl = ctypes.CDLL("libGL.so.1")
vp = ctypes.c_void_p
egl.eglGetPlatformDisplay.argtypes = [ctypes.c_int, vp, vp]
egl.eglGetPlatformDisplay.restype = vp
egl.eglInitialize.argtypes = [vp, vp, vp]
egl.eglCreateContext.argtypes = [vp, vp, vp, vp]
egl.eglCreateContext.restype = vp
egl.eglMakeCurrent.argtypes = [vp, vp, vp, vp]
gl.glGetString.restype = ctypes.c_char_p

display = egl.eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA, None, None)
if not (
    display
    and egl.eglInitialize(display, None, None)
    and egl.eglBindAPI(EGL_OPENGL_API)
):
    raise SystemExit("EGL: no surfaceless display")
context = egl.eglCreateContext(display, None, None, None)
if not (context and egl.eglMakeCurrent(display, None, None, context)):
    raise SystemExit("EGL: no OpenGL context")
print(f"renderer: {gl.glGetString(GL_RENDERER).decode()}")
print(f"version:  {gl.glGetString(GL_VERSION).decode()}")
