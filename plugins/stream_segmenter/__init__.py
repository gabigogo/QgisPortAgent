"""QGIS plugin entry point for stream_segmenter."""


def classFactory(iface):  # pylint: disable=invalid-name
    """Instantiate the plugin class for QGIS.

    The import is deferred to this function so that importing the
    ``stream_segmenter`` package (e.g. to access
    ``stream_segmenter.utils.geometry``) does not require QGIS bindings.

    Args:
        iface: QGIS interface instance supplied by QGIS at load time.

    Returns:
        StreamSegmenterPlugin: Plugin controller instance.
    """
    from .stream_segmenter_plugin import StreamSegmenterPlugin  # noqa: PLC0415

    return StreamSegmenterPlugin(iface)
