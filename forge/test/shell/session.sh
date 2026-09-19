#!/usr/bin/env bash
# Started by sway, so that cosmic-comp inherits sway's WAYLAND_DISPLAY and nests in it.
export COSMIC_BACKEND=winit
exec cosmic-comp --no-xwayland &> "/out/${RIG_TAG:-scene}-cosmic-comp.log"
