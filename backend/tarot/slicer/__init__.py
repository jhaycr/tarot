"""tarot-slice: cut individual card images out of a composition image.

Handles uniform grids as well as tilted multi-card renders and fanned/pyramid
photos of cards on a plain background — the layouts a naive grid slicer can't.
Pure Pillow + numpy (numpy is the optional ``[slice]`` extra); OpenCV is
deliberately not required. See ``tarot.slicer.core`` for the strategies and
``tarot.slicer.cli`` for the command line.
"""
